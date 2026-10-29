def load_settings(env):
    return {"port": int(env["PORT"]), "debug": env["DEBUG"] == "true"}
