import yaml
import json

def load_yaml_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_json_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f) 