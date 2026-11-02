"""Interactive mobile market routing dashboard.
Run at repository root: streamlit run routing_dashboard.py
Requires src/routes.py (route feasibility + road-mileage-aware cost) and
src/milp_solver.py (Pyomo/HiGHS). This does not modify app.py.
"""
from __future__ import annotations

import html
import math
from pathlib import Path

import folium
import altair as alt
import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from src.routes import feasible_routes, clock
from src.milp_solver import optimize_route_cover_milp

BASE = Path(__file__).resolve().parent
OSRM = "https://router.project-osrm.org"
COLORS = ["#1565c0", "#d84315", "#2e7d32", "#7b1fa2", "#00838f", "#ad1457", "#6d4c41", "#3949ab"]


def load_locations(path, required):
    frame = pd.read_csv(path)
    if not required.issubset(frame.columns):
        raise ValueError(f"{path.name} needs columns {sorted(required)}; found {list(frame.columns)}")
    frame = frame.copy()
    frame['lat'] = pd.to_numeric(frame['lat'], errors='coerce')
    frame['lon'] = pd.to_numeric(frame['lon'], errors='coerce')
    frame = frame.dropna(subset=['lat', 'lon'])
    frame = frame[frame.lat.between(-90,90) & frame.lon.between(-180,180)]
    return frame


@st.cache_data(ttl=3600, show_spinner=False)
def road_matrix(coords):
    """OSRM table, input tuple of (node_id, latitude, longitude)."""
    points = ';'.join(f'{lon:.7f},{lat:.7f}' for _, lat, lon in coords)
    response = requests.get(f'{OSRM}/table/v1/driving/{points}',
                            params={'annotations': 'duration,distance'}, timeout=45)
    response.raise_for_status()
    obj = response.json()
    if obj.get('code') != 'Ok':
        raise RuntimeError(f"OSRM table failed: {obj.get('message', obj.get('code'))}")
    times = np.array(obj['durations'], dtype=object)
    distances = np.array(obj['distances'], dtype=object)
    if any(v is None for v in times.flat) or any(v is None for v in distances.flat):
        raise RuntimeError('OSRM returned unreachable road pairs; select different sites')
    times = np.asarray(times, dtype=float) / 60  # seconds -> minutes
    distances = np.asarray(distances, dtype=float) / 1609.344  # meters -> miles
    return times, distances


@st.cache_data(ttl=3600, show_spinner=False)
def road_shape(a, b):
    url = (f'{OSRM}/route/v1/driving/'
           f'{a[1]:.7f},{a[0]:.7f};{b[1]:.7f},{b[0]:.7f}')
    response = requests.get(url, params={'overview':'full','geometries':'geojson'},timeout=35)
    response.raise_for_status()
    obj = response.json()
    if obj.get('code') != 'Ok' or not obj.get('routes'):
        raise RuntimeError('OSRM road geometry unavailable')
    return [[lat,lon] for lon,lat in obj['routes'][0]['geometry']['coordinates']]


def make_map(node_data, chosen, itinerary, include_roads=True):
    depot = node_data['DEPOT']
    fmap = folium.Map(location=[depot['lat'],depot['lon']], tiles=None, zoom_start=12)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Tiles © Esri and its data providers', name='Esri Streets', overlay=False
    ).add_to(fmap)
    folium.Marker([depot['lat'],depot['lon']], tooltip='Depot',
                  popup=html.escape(str(depot['name'])),
                  icon=folium.Icon(color='black', icon='home')).add_to(fmap)
    full_bounds = [[depot['lat'],depot['lon']]]
    for k,route in enumerate(chosen,1):
        color = COLORS[(k-1)%len(COLORS)]
        group = folium.FeatureGroup(name=f'Vehicle {k}: {" → ".join(route["stops"])}')
        sequence = ['DEPOT', *route['stops'], 'DEPOT']
        for a,b in zip(sequence,sequence[1:]):
            p = (node_data[a]['lat'],node_data[a]['lon'])
            q = (node_data[b]['lat'],node_data[b]['lon'])
            if include_roads:
                try:
                    points = road_shape(p,q)
                    fallback = False
                except (requests.RequestException,RuntimeError,ValueError):
                    points = [list(p),list(q)]
                    fallback = True
            else:
                points = [list(p),list(q)]
                fallback = True
            folium.PolyLine(points, color=color, weight=5, opacity=.85,
                            dash_array='5,8' if fallback else None,
                            tooltip=f'Vehicle {k}: {a} → {b}' + (' (approximate line)' if fallback else '')).add_to(group)
            full_bounds.extend(points)
        for order,stop in enumerate(route['stops'],1):
            pos = node_data[stop]
            schedule = next(s for s in itinerary if s['vehicle']==k and s['site_id']==stop)
            desc = (f'<b>{html.escape(str(pos["name"]))}</b><br>Vehicle {k}, Stop {order}'
                    f'<br>Arrival: {schedule["arrival"]}<br>Service: {schedule["service_start"]}–{schedule["service_end"]}')
            dot = (f'<div style="background:{color};color:white;border:2px solid white;border-radius:50%;'
                   f'width:29px;height:29px;text-align:center;line-height:25px;font-weight:bold">{order}</div>')
            folium.Marker([pos['lat'],pos['lon']], icon=folium.DivIcon(html=dot),
                          popup=folium.Popup(desc,max_width=300),tooltip=f'Vehicle {k}: {stop}').add_to(group)
        group.add_to(fmap)
    fmap.fit_bounds(full_bounds)
    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap


def main():
    st.set_page_config(page_title='Mobile Market Routing',layout='wide')
    st.title('Mobile Market Fleet Routing & Scheduling')
    st.caption('Independent prototype · real candidate coordinates · OSRM road estimates · Pyomo/HiGHS MILP')
    markets_path = BASE / 'outputs/markets_clean.csv'
    pantry_path = BASE / 'outputs/pantry_depots.csv'
    if not markets_path.exists() or not pantry_path.exists():
        st.warning('Prepared Detroit input CSVs are not installed. Loading the six-site demonstration dataset instead; add outputs/markets_clean.csv and outputs/pantry_depots.csv to use your 79/133 source records.')
        markets_path = BASE / 'demo_data/markets_clean.csv'
        pantry_path = BASE / 'demo_data/pantry_depots.csv'
        if not markets_path.exists() or not pantry_path.exists():
            st.error('No input datasets. Add the prepared CSVs under outputs/.')
            st.stop()
    try:
        markets = load_locations(markets_path, {'site_id','lat','lon'})
        pantries = load_locations(pantry_path, {'lat','lon'})
    except Exception as exc:
        st.error(str(exc)); st.stop()
    if markets.empty or pantries.empty:
        st.error('One or both location datasets have no valid coordinates'); st.stop()
    markets['site_id'] = markets.site_id.astype(str)
    markets = markets.drop_duplicates('site_id')
    market_fallback = pd.Series('Market ' + markets.site_id.astype(str), index=markets.index)
    markets['name'] = markets['name'].replace('',pd.NA).fillna(market_fallback) if 'name' in markets else market_fallback
    pantries = pantries.reset_index(drop=True)
    pantry_fallback = pd.Series([f'Pantry {i+1}' for i in range(len(pantries))],index=pantries.index)
    pantries['name'] = pantries['name'].replace('',pd.NA).fillna(pantry_fallback) if 'name' in pantries else pantry_fallback

    with st.sidebar:
        st.header('Scenario configuration')
        depot_mode = st.radio('Depot', ['Pantry candidate','Fixed coordinates'])
        if depot_mode == 'Pantry candidate':
            depot_row = st.selectbox('Select pantry',list(range(len(pantries))),
                format_func=lambda i: f'{i}: {pantries.iloc[i]["name"]} ({pantries.iloc[i]["lat"]:.4f}, {pantries.iloc[i]["lon"]:.4f})',
                index=min(11,len(pantries)-1))
            depot_lat, depot_lon = float(pantries.iloc[depot_row].lat),float(pantries.iloc[depot_row].lon)
            depot_name = str(pantries.iloc[depot_row]['name'])
        else:
            depot_lat = st.number_input('Depot latitude',value=42.388689,format='%.6f')
            depot_lon = st.number_input('Depot longitude',value=-83.104576,format='%.6f')
            depot_name = 'Custom depot'
        n = st.slider('Nearest stops to preselect',1,min(15,len(markets)),min(6,len(markets)))
        approx = (markets.lat-depot_lat)**2 + ((markets.lon-depot_lon)*math.cos(math.radians(depot_lat)))**2
        nearby = markets.assign(_dist=approx).sort_values('_dist')
        names = {r.site_id:f'{r.site_id} — {r["name"]}' for _,r in markets.iterrows()}
        selected = st.multiselect('Market stops', options=nearby.site_id.tolist(),
            default=nearby.site_id.head(n).tolist(),format_func=lambda s:names[s])
        st.divider()
        fleet_min = st.number_input('Minimum vehicles',min_value=1,max_value=30,value=3)
        fleet_max = st.number_input('Maximum vehicles',min_value=1,max_value=30,value=5)
        service = st.number_input('Service minutes / market',min_value=15,max_value=480,value=120,step=15)
        start_hour = st.number_input('Daily start hour (24h)',0,23,8)
        end_hour = st.number_input('Daily end hour (24h)',0,23,18)
        st.divider()
        fixed = st.number_input('Vehicle deployment cost ($)',min_value=0.0,value=50.0)
        cost_mile = st.number_input('Driving cost ($/mile)',min_value=0.0,value=0.80,step=0.10)
        labor = st.number_input('Driver cost ($/hour)',min_value=0.0,value=20.0)
        road_shapes = st.checkbox('Show street-following geometry',value=True)
        clicked = st.button('Optimize routes',type='primary',use_container_width=True)
        st.caption('Click Optimize again after changing settings. The previous solution remains visible until then.')

    st.info('Market and pantry coordinates are candidate locations; pantries are not verified dispatch facilities. Service windows and cost coefficients are planning assumptions.')
    signature = (depot_mode, round(depot_lat,6), round(depot_lon,6), tuple(selected),
                 int(fleet_min), int(fleet_max), int(service), int(start_hour), int(end_hour),
                 float(fixed), float(cost_mile), float(labor))
    if clicked:
        if not selected:
            st.error('Select at least one market.')
        elif fleet_min > fleet_max or start_hour >= end_hour:
            st.error('Fleet bounds or operating hours are invalid.')
        elif math.ceil(len(selected)/2) > fleet_max or fleet_min > len(selected):
            st.error('The fleet cannot cover the selected markets with at most two stops per vehicle.')
        else:
            focus = markets.set_index('site_id').loc[selected]
            nodes = {'DEPOT':{'name':depot_name,'lat':depot_lat,'lon':depot_lon}}
            for site,row in focus.iterrows():
                nodes[site] = {'name':str(row['name']),'lat':float(row.lat),'lon':float(row.lon)}
            ids = list(nodes)
            coords = tuple((name,nodes[name]['lat'],nodes[name]['lon']) for name in ids)
            try:
                with st.spinner('Calculating road distances, checking route schedules, solving MILP…'):
                    times, distances = road_matrix(coords)
                    travel = {(a,b):float(times[i,j]) for i,a in enumerate(ids) for j,b in enumerate(ids)}
                    market_specs = {site:{'open':int(start_hour*60),'close':int(end_hour*60),
                                          'service':int(service)} for site in selected}
                    candidates = feasible_routes(market_specs,travel,depart=int(start_hour*60),
                                                 shift_end=int(end_hour*60),max_stops=2)
                    index = {name:i for i,name in enumerate(ids)}
                    for route in candidates:
                        seq=['DEPOT',*route['stops'],'DEPOT']
                        route['distance_miles']=sum(float(distances[index[a],index[b]])
                            for a,b in zip(seq,seq[1:]))
                    if not candidates:
                        st.error('No feasible individual routes for this schedule.')
                    else:
                        result = optimize_route_cover_milp(market_specs,candidates,
                            fleet_min=int(fleet_min),fleet_max=int(fleet_max),
                            fixed_vehicle_cost=float(fixed),cost_per_mile=float(cost_mile),
                            driver_hourly_rate=float(labor),solver_name='appsi_highs')
                        if result is None:
                            st.error('MILP infeasible: adjust the fleet or the operating window.')
                        else:
                            obj,chosen=result
                            visits=[];route_rows=[];schedule_rows=[]
                            for k,r in enumerate(chosen,1):
                                route_rows.append({'Vehicle':k,'Route':' → '.join(['DEPOT',*r['stops'],'DEPOT']),
                                    'Stops':len(r['stops']),'Miles':r['distance_miles'],
                                    'Driving (min)':r['total_drive_min'],'Waiting (min)':r['total_wait_min'],
                                    'Duty (hours)':r['duty_hours'],'Fixed ($)':r['fixed_cost'],
                                    'Mileage ($)':r['distance_cost'],'Labor ($)':r['labor_cost'],
                                    'Total ($)':r['total_cost'],'Return':clock(r['return_time'])})
                                for s in r['itinerary']:
                                    visits.append({'vehicle':k,'site_id':s['site_id'],
                                      'arrival':clock(s['arrival']),'service_start':clock(s['start']),
                                      'service_end':clock(s['finish']),'waiting_minutes':s['waiting']})
                                    schedule_rows.append({'Vehicle':f'Vehicle {k}',
                                      'Market':s['site_id'],'Start':s['start']/60,
                                      'End':s['finish']/60,'Type':'Market service'})
                            st.session_state['last_solution']={
                                'signature':signature,'nodes':nodes,'chosen':chosen,'visits':visits,
                                'routes':route_rows,'schedule':schedule_rows,'objective':obj,
                                'feasible':len(candidates),'possible':len(selected)**2,
                                'selected':list(selected),'start':start_hour*60,'end':end_hour*60}
            except Exception as exc:
                st.error(f'Could not complete optimization: {exc}')
    solution = st.session_state.get('last_solution')
    if not solution:
        st.write(f'Loaded **{len(markets)}** market candidates and **{len(pantries)}** pantry candidates. Configure your scenario and click **Optimize routes**.')
        return
    if signature != solution['signature']:
        st.warning('Settings changed since the last optimization. The results below belong to the previous scenario. Click Optimize routes to refresh.')
    chosen=solution['chosen']; visits=solution['visits']; nodes=solution['nodes']
    rows=pd.DataFrame(solution['routes'])
    objective=float(solution['objective'])
    st.subheader('Decision-maker overview')
    a,b,c,d=st.columns(4)
    a.metric('Estimated daily cost',f'${objective:,.2f}')
    b.metric('Vehicles deployed',len(chosen))
    c.metric('Markets served',len(visits))
    d.metric('Total miles',f'{rows["Miles"].sum():.1f}')
    st.caption(f'{solution["feasible"]} of {solution["possible"]} possible directed routes are schedule-feasible. Costs are illustrative, not measured expenditures.')
    map_tab, insight_tab, detail_tab, validate_tab = st.tabs(['Route map','Costs & insights','Vehicle schedules','Validation & export'])
    with map_tab:
        st.caption('Vehicle colors identify each route. Dashed links mean OSRM geometry was unavailable and a straight-line sketch is shown.')
        try:
            fmap=make_map(nodes,chosen,visits,road_shapes)
            components.html(fmap.get_root().render(),height=640,scrolling=False)
        except Exception as exc:
            st.warning(f'Map could not be rendered: {exc}. Solver outputs are still shown in the other tabs.')
    with insight_tab:
        fixed_total=rows['Fixed ($)'].sum()
        mileage_total=rows['Mileage ($)'].sum()
        labor_total=rows['Labor ($)'].sum()
        breakdown=pd.DataFrame({'Component':['Vehicle deployment','Mileage','Driver labor'],
                                'Cost ($)':[fixed_total,mileage_total,labor_total]})
        st.markdown('**Where operating costs come from**')
        st.altair_chart(alt.Chart(breakdown).mark_bar().encode(
            x=alt.X('Component:N',sort=None,title=None),y=alt.Y('Cost ($):Q'),
            tooltip=['Component:N',alt.Tooltip('Cost ($):Q',format='.2f')]
        ).properties(height=280),use_container_width=True)
        st.markdown('**Cost by vehicle**')
        vehicle_cost=rows[['Vehicle','Fixed ($)','Mileage ($)','Labor ($)']].melt(
            id_vars='Vehicle',var_name='Component',value_name='USD')
        vehicle_cost['Vehicle']=vehicle_cost['Vehicle'].map(lambda x:f'Vehicle {x}')
        st.altair_chart(alt.Chart(vehicle_cost).mark_bar().encode(
            x=alt.X('Vehicle:N',title=None),y='USD:Q',color='Component:N',
            tooltip=['Vehicle','Component',alt.Tooltip('USD:Q',format='.2f')]
        ).properties(height=280),use_container_width=True)
        expensive=rows.loc[rows['Total ($)'].idxmax()]
        st.write(f'**At a glance:** {len(chosen)} vehicles cover {len(visits)} selected markets. '
                 f'Labor accounts for {100*labor_total/objective:.1f}% of estimated operating cost '
                 f'when total cost is positive.' if objective>0 else
                 'All entered cost rates are zero; no cost breakdown is meaningful.')
        st.write(f'Vehicle {int(expensive["Vehicle"])} has the highest modeled route cost '
                 f'(${expensive["Total ($)"]:.2f}); this reflects its driving, waiting, and duty time, not demand.')
        st.caption('These are descriptive findings for the current optimized scenario—not comparisons to an alternative plan.')
    with detail_tab:
        st.markdown('**Market service timeline**')
        timeline=pd.DataFrame(solution['schedule'])
        if not timeline.empty:
            chart=alt.Chart(timeline).mark_bar(size=20).encode(
                y=alt.Y('Vehicle:N',sort=None),x=alt.X('Start:Q',title='Time of day (24-hour clock)',scale=alt.Scale(domain=[solution['start']/60,solution['end']/60])),
                x2='End:Q',color=alt.Color('Market:N'),
                tooltip=['Vehicle','Market',alt.Tooltip('Start:Q',format='.2f'),alt.Tooltip('End:Q',format='.2f')]
            ).properties(height=max(180,len(chosen)*55))
            st.altair_chart(chart,use_container_width=True)
        st.dataframe(rows.round(2),use_container_width=True,hide_index=True)
        st.markdown('**Stop-by-stop itinerary**')
        st.dataframe(pd.DataFrame(visits),use_container_width=True,hide_index=True)
    with validate_tab:
        served=[v['site_id'] for v in visits]
        expected=solution['selected']
        exactly_once=(len(served)==len(expected) and set(served)==set(expected)
                      and len(served)==len(set(served)))
        kmin=solution['signature'][4];kmax=solution['signature'][5]
        fleet_ok=kmin <= len(chosen) <= kmax
        stops_ok=all(1<=len(r['stops'])<=2 for r in chosen)
        shift_ok=all(r['return_time']<=solution['end']+1e-7 for r in chosen)
        dollar_ok=abs(rows['Total ($)'].sum()-objective)<1e-4
        schedule_ok=all(s['finish']<=solution['end']+1e-7 and
                        s['start']>=solution['start']-1e-7
                        for r in chosen for s in r['itinerary'])
        checks={'Every market exactly once':exactly_once,'Fleet bounds':fleet_ok,
            'At most two markets per vehicle':stops_ok,'Depot return by shift end':shift_ok,
            'Market service within planning window':schedule_ok,
            'Sum of route costs equals MILP objective':dollar_ok}
        st.dataframe(pd.DataFrame([{'Check':name,'Result':'PASS' if ok else 'FAIL'}
                     for name,ok in checks.items()]),hide_index=True,use_container_width=True)
        if all(checks.values()):
            st.success('All six solution checks passed for the modeled assumptions.')
        else:
            st.error('One or more validation checks failed. Do not use these results operationally.')
        st.download_button('Download vehicle routes CSV',rows.to_csv(index=False),
                           file_name='optimized_routes.csv',mime='text/csv')
        st.download_button('Download stop itinerary CSV',pd.DataFrame(visits).to_csv(index=False),
                           file_name='itinerary.csv',mime='text/csv')
        st.caption('Limitations: public routing estimates exclude live traffic; no demand or capacity; pantry eligibility and posted service appointments are not verified.')


if __name__ == '__main__':
    main()
