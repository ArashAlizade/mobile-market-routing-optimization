import unittest
import pandas as pd
from src.location_data import market_locations, pantry_depots

class TestLocations(unittest.TestCase):
    def test_market_validation(self):
        df = pd.DataFrame({'site_id':[1,2,2], 'lat':[42.3,999,42.4], 'lon':[-83.1,-83.2,-83.3]})
        result=market_locations(df)
        self.assertEqual(len(result),2)
    def test_explicit_pantry_filter(self):
        df = pd.DataFrame({'kind':['Food Pantry','Grocery Store','pantry'],
                           'lat':[42.3,42.4,42.5], 'lon':[-83.1,-83.2,-83.3]})
        result=pantry_depots(df,category_col='kind',lat_col='lat',lon_col='lon')
        self.assertEqual(len(result),2)
    def test_missing_column(self):
        with self.assertRaises(ValueError):
            market_locations(pd.DataFrame({'lat':[42.3],'lon':[-83.1]}))
if __name__ == '__main__': unittest.main()
