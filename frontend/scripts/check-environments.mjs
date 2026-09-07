// Browser UI checks with synthetic Cognito sessions and intercepted API fixtures.
// Never uses live credentials or calls the production API.
import { chromium } from 'playwright';
import { readFile,mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true});
const dist={AWS:'EKS',AZURE:'AKS',GCP:'GKE',OCI:'OKE'};
const rows=Object.entries(dist).map(([provider,distribution],i)=>({environmentId:`ENV-demo-${i}`,customerId:'CUS-demo',customerName:'Example Industries',cloudProvider:provider,kubernetesDistribution:distribution,environmentName:`Production ${distribution}`,environmentType:'PROD',status:i?'DRAFT':'ACTIVE',version:1,approvedVersion:i?null:1,createdAt:'2026-09-07T10:00:00Z',updatedAt:'2026-09-07T10:00:00Z',description:'Approved infrastructure baseline',configurationSchemaVersion:'1.0',configuration:{location:{region:provider==='AWS'?'ap-south-1':'example-region'}},workflow:{},createdBy:'browser-test'}));
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const base=process.env.TEST_BASE_URL||'http://127.0.0.1:3101';
try{
 await page.addInitScript(()=>{
  const claims={sub:'browser-test',username:'browser-test',roles:JSON.stringify(['CLOUD_ENGINEER','PLATFORM_ARCHITECT']),customer_ids:'[]',platform_scope:'true',customer_create:'true',exp:Math.floor(Date.now()/1000)+3600,iat:Math.floor(Date.now()/1000),auth_time:Math.floor(Date.now()/1000),iss:'https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_GtWAW9Owz'};
  const token=use=>[btoa(JSON.stringify({alg:'RS256',typ:'JWT'})),btoa(JSON.stringify({...claims,token_use:use,aud:'ci-public-client',client_id:'ci-public-client',email:'preview@example.com',name:'Preview Engineer'})),'synthetic-test-signature'].join('.');
  const prefix='CognitoIdentityServiceProvider.ci-public-client';sessionStorage.setItem(prefix+'.LastAuthUser','browser-test');sessionStorage.setItem(prefix+'.browser-test.accessToken',token('access'));sessionStorage.setItem(prefix+'.browser-test.idToken',token('id'));sessionStorage.setItem(prefix+'.browser-test.clockDrift','0');
 });
 const pagination=items=>({items,pagination:{page:0,pageSize:20,totalElements:items.length,totalPages:1}});
 await page.route('**/api/platform/**',async route=>{
  const url=new URL(route.request().url());const path=url.pathname.replace('/api/platform','');let data;
  if(path==='/customers')data=pagination([{customerId:'CUS-demo',name:'Example Industries',status:'ACTIVE',version:1,cloudProviders:Object.keys(dist)}]);
  else if(path==='/environments/metadata')data={environmentTypes:['DEV','TEST','PROD'],distributions:Object.entries(dist).map(([cloudProvider,kubernetesDistribution])=>({cloudProvider,kubernetesDistribution,schemaVersions:['1.0']}))};
  else if(path.startsWith('/environments/configuration-schemas/')){const distribution=path.split('/')[3];data=JSON.parse(await readFile(`../src/navigan/modules/environment_management/schemas/${distribution.toLowerCase()}-1.0.json`,'utf8'));}
  else if(path==='/environments'&&route.request().method()==='POST'){
   const input=route.request().postDataJSON();const row={...rows[1],...input,environmentId:'ENV-created',status:'DRAFT',approvedVersion:null};rows.push(row);return route.fulfill({status:201,json:row});
  }else if(path==='/environments')data=pagination(rows);
  else {const [, ,id,kind]=path.split('/');const row=rows.find(r=>r.environmentId===id);data=kind?pagination([]):row;}
  await route.fulfill({status:data?200:404,json:data||{error:{code:'NOT_FOUND',message:'Missing fixture',details:{},correlationId:'test'}}});
 });
 await mkdir('test-results',{recursive:true});
 await page.goto(base+'/environments');await page.getByRole('link',{name:'Production EKS',exact:true}).waitFor();
 await page.screenshot({path:'test-results/environments-desktop.png',fullPage:true});
 await page.getByRole('link',{name:'Create environment',exact:true}).click();
 await page.getByLabel('Customer *',{exact:true}).selectOption('CUS-demo');
 for(const [provider,label] of Object.entries({AWS:'Account ID',AZURE:'Tenant ID',GCP:'Project ID',OCI:'Tenancy OCID'})){
  await page.getByLabel('Kubernetes distribution *').selectOption(provider);
  await page.getByLabel(new RegExp(label)).waitFor();
  assert.equal(await page.getByLabel(new RegExp(label)).count(),1);
 }
 await page.screenshot({path:'test-results/environment-oke-form.png',fullPage:true});
 await page.getByLabel('Environment name *',{exact:true}).fill('OCI Sandbox');await page.getByLabel('Environment type *',{exact:true}).selectOption('DEV');
 await page.getByRole('button',{name:'Save draft',exact:true}).click();await page.getByRole('heading',{name:'OCI Sandbox',exact:true}).waitFor();
 await page.screenshot({path:'test-results/environment-details.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.goto(base+'/environments');await page.getByRole('link',{name:'Production EKS',exact:true}).waitFor();
 await page.screenshot({path:'test-results/environments-mobile.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
 assert.deepEqual(errors,[]);
 console.log('Environment list, four dynamic forms, draft creation and mobile layout passed.');
}finally{await browser.close();}
