"""One-shot: copy tunables out of an old type_config.py into JSON profiles."""
import ast, json, os, sys

IDENTITY = {
    "speed_base","turn_base","size","strength_range","agility_range","bravery_range",
    "prey","fear","display_name","icon","color",
}

def extract(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    blob = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TYPE_DEFAULTS":
                    blob = ast.literal_eval(node.value)
    return blob or {}

def main(old_path="type_config.py.bak"):
    data = extract(old_path if os.path.exists(old_path) else "type_config.py")
    root = os.path.join(os.path.dirname(__file__) or ".", "strategies", "types")
    for name, d in data.items():
        weights = {k: (list(v) if isinstance(v, tuple) else v)
                   for k, v in d.items() if k not in IDENTITY}
        dest = os.path.join(root, name, "_profile.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        json.dump({"type": name, "weights": weights}, open(dest, "w"), indent=2)
        print("wrote", dest, "keys", len(weights))

if __name__ == "__main__":
    main(*sys.argv[1:])
