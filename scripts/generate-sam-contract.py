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
    value={'version':1,'sources':{},'parameters':list(root['Parameters']),
           'requiredParameters':[k for k,v in root['Parameters'].items() if 'Default' not in v],'routes':{}}
    paths=['infrastructure/template.yaml']+['infrastructure/modules/'+f+'/template.yaml' for f in capture.MODULES.values()]
    for path in paths:value['sources'][path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    for module,folder in capture.MODULES.items():
        template=load_template(ROOT/'infrastructure/modules'/folder/'template.yaml')
        value['routes'][module]={'Resources':{k:{'Type':v['Type'],'Properties':{'RouteKey':v['Properties']['RouteKey']}}
            for k,v in template['Resources'].items() if v['Type']=='AWS::ApiGatewayV2::Route'}}
    return value

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--write',action='store_true');args=parser.parse_args()
    path=ROOT/'infrastructure/sam-reconciliation-contract.json';value=build()
    if args.write:path.write_text(json.dumps(value,indent=2)+'\n');print('SAM source contract regenerated. Review it with the template changes.');return
    if not path.is_file() or json.loads(path.read_text())!=value:raise SystemExit('SAM contract differs from source; regenerate with --write and review.')
    print('SAM source contract matches templates.')

if __name__=='__main__':main()
