class Inventory:
    def __init__(self):
        self._stock = {}

    def add(self, name, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._stock[name] = self._stock.get(name, 0) + qty

    def remove(self, name, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        if self._stock.get(name, 0) < qty:
            raise KeyError(f"not enough {name!r} in stock")
        self._stock[name] -= qty
        if self._stock[name] == 0:
            del self._stock[name]

    def count(self, name):
        return self._stock.get(name, 0)

    def items(self):
        return dict(self._stock)
