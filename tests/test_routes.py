import unittest
from src.routes import enumerate_routes,evaluate_route,feasible_routes,optimize_route_cover
class TestRouting(unittest.TestCase):
    def setUp(self):
        self.m={'A':{'open':540,'close':660,'service':120},'B':{'open':600,'close':720,'service':120}}
        self.t={('DEPOT','A'):20,('A','DEPOT'):20,('DEPOT','B'):20,('B','DEPOT'):20,('A','B'):30,('B','A'):30}
    def test_candidates(self):
        self.assertEqual(len(list(enumerate_routes(self.m))),4)
    def test_conflict(self):
        self.assertIsNone(evaluate_route(('A','B'),self.m,self.t))
    def test_fleet(self):
        r=feasible_routes(self.m,self.t)
        answer=optimize_route_cover(self.m,r,2,2)
        self.assertIsNotNone(answer)
        self.assertEqual(len(answer[1]),2)
if __name__=='__main__': unittest.main()
