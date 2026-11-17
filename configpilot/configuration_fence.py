"""Optional read-only cluster snapshots before and after a controlled run."""
import json
import subprocess


def capture_configuration(model):
    result = {}
    kinds = {'VirtualService': 'virtualservices.networking.istio.io',
             'DestinationRule': 'destinationrules.networking.istio.io',
             'Gateway': 'gateways.networking.istio.io', 'Service': 'services'}
    for resource in model['resources']:
        if resource['kind'] not in {'VirtualService', 'DestinationRule', 'Gateway', 'Service'}:
            continue
        command = ['kubectl', 'get', kinds[resource['kind']]+'/'+resource['name'],
                   '-n', resource['namespace'], '-o', 'json']
        try:
            process = subprocess.run(command, text=True, encoding='utf-8', capture_output=True, timeout=15, check=True)
            value = json.loads(process.stdout)
            metadata = value['metadata']
            if not metadata.get('uid') or not metadata.get('resourceVersion'):
                raise ValueError('live resource has no UID or resourceVersion')
            result[resource['id']] = {'uid': metadata['uid'], 'resourceVersion': metadata['resourceVersion'],
                                      'spec': value.get('spec', {})}
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError('configuration snapshot failed for '+resource['id']) from exc
    return result
