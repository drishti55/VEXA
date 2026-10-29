import inspect
from pydantic import BaseModel, create_model

def generate_schema(func):
    sig = inspect.signature(func)
    fields = {}
    for name, param in sig.parameters.items():
        if name in ("self", "args", "kwargs"):
            continue
        annotation = param.annotation if param.annotation != inspect.Parameter.empty else str
        default = param.default if param.default != inspect.Parameter.empty else ...
        fields[name] = (annotation, default)
    
    return create_model(f"{func.__name__}_schema", **fields)

class B:
    def run(self):
        pass

schema = generate_schema(B().run)
print(schema.model_json_schema())
