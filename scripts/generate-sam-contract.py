#!/usr/bin/env python3
"""Validate (default) or regenerate (--write) the public SAM route contract.

Developer tool: requires PyYAML. The AWS capture uses the resulting JSON and the
standard library only, so it does not require YAML support in deployment venvs.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sam_capture_contract',ROOT/'scripts/reconcile-sam.py')
capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)

def load_template(path):
    import yaml
    class Loader(yaml.SafeLoader):pass
    def intrinsic(loader,tag,node):
        value=loader.construct_scalar(node) if isinstance(node,yaml.ScalarNode) else loader.construct_sequence(node) if isinstance(node,yaml.SequenceNode) else loader.construct_mapping(node)
        if tag=='GetAtt' and isinstance(value,str):value=value.split('.',1)
        return {tag if tag in ('Ref','Condition') else 'Fn::'+tag:value}
    Loader.add_multi_constructor('!',intrinsic)
    return yaml.load(path.read_text(),Loader=Loader)

def build():
    root=load_template(ROOT/'infrastructure/template.yaml')
    value={'version':2,'sources':{},'parameters':list(root['Parameters']),
           'requiredParameters':[k for k,v in root['Parameters'].items() if 'Default' not in v],
           'routes':{'dev':[],'prod':[]}}
    companion='infrastructure/companion/dev-route-ownership.yaml'
    paths=['infrastructure/template.yaml']+['infrastructure/modules/'+f+'/template.yaml' for f in capture.MODULES.values()]+[companion]
    for path in paths:value['sources'][path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    for module,folder in capture.MODULES.items():
        template=load_template(ROOT/'infrastructure/modules'/folder/'template.yaml')
        for logical,resource in template['Resources'].items():
            if resource['Type']!='AWS::ApiGatewayV2::Route':continue
            condition=resource.get('Condition')
            environments={'IsDev':['dev'],'IsProd':['prod'],None:['dev','prod']}.get(condition)
            if environments is None:raise RuntimeError('Unsupported route environment condition: '+str(condition))
            for environment in environments:
                value['routes'][environment].append({'module':module,'sourceLogicalId':logical,
                    'routeKey':resource['Properties']['RouteKey'],
                    'owner':{'captureStack':'root--'+module,'logicalId':logical}})
    companion_template=load_template(ROOT/companion)
    for logical,resource in companion_template['Resources'].items():
        if resource['Type']!='AWS::ApiGatewayV2::Route':continue
        module=next((name for name in capture.MODULES if logical.startswith(name)),None)
        if not module:raise RuntimeError('Companion route is not namespaced by a known module: '+logical)
        value['routes']['dev'].append({'module':module,'sourceLogicalId':logical[len(module):],
            'routeKey':resource['Properties']['RouteKey'],
            'owner':{'captureStack':'companion--sam-route-ownership','logicalId':logical}})
    for environment in value['routes']:
        value['routes'][environment].sort(key=lambda route:(route['module'],route['routeKey'],route['owner']['logicalId']))
        keys=[route['routeKey'] for route in value['routes'][environment]]
        if len(keys)!=len(set(keys)):raise RuntimeError('Duplicate active route key for '+environment)
    return value

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--write',action='store_true');args=parser.parse_args()
    path=ROOT/'infrastructure/sam-reconciliation-contract.json';value=build()
    if args.write:path.write_text(json.dumps(value,indent=2)+'\n');print('SAM source contract regenerated. Review it with the template changes.');return
    if not path.is_file() or json.loads(path.read_text())!=value:raise SystemExit('SAM contract differs from source; regenerate with --write and review.')
    print('SAM source contract matches templates.')

if __name__=='__main__':main()
