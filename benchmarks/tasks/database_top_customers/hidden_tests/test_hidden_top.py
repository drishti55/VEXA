from orders import connect, top_customers

def test_top_two():
    assert top_customers(connect(), 2) == [('cy', 45.0), ('ada', 25.0)]

def test_tie_and_exclusion():
    assert top_customers(connect(), 10) == [('cy', 45.0), ('ada', 25.0), ('bob', 25.0)]
