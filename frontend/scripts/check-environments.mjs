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
 const response=await page.request.get(base+'/api/runtime-config');
 assert.equal(response.status(),200,'Browser fixture requires valid public runtime settings.');
 const {oidcClientId,oidcAuthority}=await response.json();
 assert.ok(oidcClientId&&oidcAuthority,'Browser fixture requires configured Cognito identity.');
 await page.addInitScript(({oidcClientId,oidcAuthority})=>{
  const claims={sub:'browser-test',username:'browser-test',roles:JSON.stringify(['CLOUD_ENGINEER','PLATFORM_ARCHITECT']),customer_ids:'[]',platform_scope:'true',customer_create:'true',exp:Math.floor(Date.now()/1000)+3600,iat:Math.floor(Date.now()/1000),auth_time:Math.floor(Date.now()/1000),iss:oidcAuthority};
  const token=use=>[btoa(JSON.stringify({alg:'RS256',typ:'JWT'})),btoa(JSON.stringify({...claims,token_use:use,aud:oidcClientId,client_id:oidcClientId,email:'preview@example.com',name:'Preview Engineer'})),'synthetic-test-signature'].join('.');
  const prefix='CognitoIdentityServiceProvider.'+oidcClientId;sessionStorage.setItem(prefix+'.LastAuthUser','browser-test');sessionStorage.setItem(prefix+'.browser-test.accessToken',token('access'));sessionStorage.setItem(prefix+'.browser-test.idToken',token('id'));sessionStorage.setItem(prefix+'.browser-test.clockDrift','0');
 },{oidcClientId,oidcAuthority});
 const pagination=items=>({items,pagination:{page:0,pageSize:20,totalElements:items.length,totalPages:1}});
 await page.route('**/api/platform/**',async route=>{
  const url=new URL(route.request().url());const path=url.pathname.replace('/api/platform','');let data;
  if(path==='/access/me')data={user:{userId:'browser-test',displayName:'Preview Engineer'},authorizationRevision:1,privileges:['environment.view','environment.create','environment.edit','environment.submit','customer.view'],scopes:[{type:'PLATFORM'}],source:'DYNAMIC'};
  else if(path==='/customers')data=pagination([{customerId:'CUS-demo',name:'Example Industries',status:'ACTIVE',version:1,cloudProviders:Object.keys(dist)}]);
  else if(path==='/environments/metadata')data={environmentTypes:['DEV','TEST','PROD'],distributions:Object.entries(dist).map(([cloudProvider,kubernetesDistribution])=>({cloudProvider,kubernetesDistribution,schemaVersions:['1.0']}))};
  else if(path.startsWith('/environments/configuration-schemas/')){const distribution=path.split('/')[3];data=JSON.parse(await readFile(`../src/navigan/modules/environment_management/schemas/${distribution.toLowerCase()}-1.0.json`,'utf8'));}
  else if(path==='/environments'&&route.request().method()==='POST'){
   const input=route.request().postDataJSON();const row={...rows[0],...input,environmentId:'ENV-created',status:'DRAFT',approvedVersion:null};rows.push(row);return route.fulfill({status:201,json:row});
  }else if(path==='/environments')data=pagination(rows.filter(row=>(!url.searchParams.get('status')||row.status===url.searchParams.get('status'))&&(!url.searchParams.get('cloudProvider')||row.cloudProvider===url.searchParams.get('cloudProvider'))));
  else {const [, ,id,kind]=path.split('/');const row=rows.find(r=>r.environmentId===id);data=kind?pagination([]):row;}
  await route.fulfill({status:data?200:404,json:data||{error:{code:'NOT_FOUND',message:'Missing fixture',details:{},correlationId:'test'}}});
 });
 await mkdir('test-results',{recursive:true});
 await page.goto(base+'/environments');await page.getByRole('link',{name:'Open Production EKS',exact:true}).waitFor();
 await page.screenshot({path:'test-results/environments-desktop.png',fullPage:true});
 await page.getByRole('link',{name:'New environment',exact:true}).click();
 await page.getByLabel(/^Customer/).selectOption('CUS-demo');
 await page.getByLabel(/AWS account ID/i).waitFor();
 assert.equal(await page.getByLabel(/AWS account ID/i).count(),1);
 await page.screenshot({path:'test-results/environment-eks-form.png',fullPage:true});
 await page.getByLabel(/^Environment name/).fill('AWS Sandbox');await page.getByLabel(/^Environment type/).selectOption('DEV');
 await page.getByRole('button',{name:'Save as Draft',exact:true}).click();await page.getByRole('heading',{name:'AWS Sandbox',exact:true}).waitFor();
 await page.screenshot({path:'test-results/environment-details.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.goto(base+'/environments');await page.getByRole('link',{name:'Open Production EKS',exact:true}).waitFor();
 await page.screenshot({path:'test-results/environments-mobile.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
 assert.deepEqual(errors,[]);
 console.log('Environment list across four providers, AWS draft creation and mobile layout passed.');
}catch(error){
 await page.screenshot({path:'test-results/environment-failure.png',fullPage:true});
 console.error('Browser fixture page:',await page.locator('body').innerText());
 throw error;
}finally{await browser.close();}
