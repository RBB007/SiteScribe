const DB_NAME="mka-site-report-offline", VERSION=1;
const openDB=()=>new Promise((resolve,reject)=>{
  const request=indexedDB.open(DB_NAME,VERSION);
  request.onupgradeneeded=()=>{const db=request.result;
    if(!db.objectStoreNames.contains("queue"))db.createObjectStore("queue",{keyPath:"id",autoIncrement:true});
    if(!db.objectStoreNames.contains("cache"))db.createObjectStore("cache");
  };
  request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
});
async function store(name,mode,fn){const db=await openDB();return new Promise((resolve,reject)=>{
  const tx=db.transaction(name,mode), result=fn(tx.objectStore(name));
  tx.oncomplete=()=>resolve(result?.result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
});}
const getAll=()=>store("queue","readonly",s=>s.getAll());
const pendingCount=async()=>(await getAll()).length;
async function notify(mode){const count=await pendingCount();
  window.dispatchEvent(new CustomEvent("offline-status",{detail:{mode,count,online:navigator.onLine}}));}
async function cacheSet(key,value){await store("cache","readwrite",s=>s.put(value,key));}
async function cacheGet(key){return store("cache","readonly",s=>s.get(key));}
function packBody(body){
  if(body instanceof FormData)return {type:"form",value:[...body.entries()]};
  if(typeof body==="string")return {type:"text",value:body};
  return {type:"none",value:null};
}
function unpackBody(body){if(!body||body.type==="none")return undefined;
  if(body.type==="text")return body.value;
  const form=new FormData();body.value.forEach(([key,value])=>form.append(key,value));return form;
}
async function enqueue(url,options={}){
  const headers={};new Headers(options.headers||{}).forEach((v,k)=>headers[k]=v);
  await store("queue","readwrite",s=>s.add({url,method:options.method||"POST",headers,body:packBody(options.body),created:Date.now()}));
  await notify("offline");return {queued:true};
}
async function request(url,options={}){
  const method=(options.method||"GET").toUpperCase(), canQueue=!["GET","HEAD"].includes(method)&&options.queue!==false;
  if(!navigator.onLine&&canQueue)return enqueue(url,options);
  try{const response=await fetch(url,options);return response;}
  catch(error){if(canQueue)return enqueue(url,options);throw error;}
}
let flushing=false;
async function flush(){
  if(flushing||!navigator.onLine)return;flushing=true;await notify("saving");
  try{for(const job of await getAll()){
    const options={method:job.method,headers:job.headers,body:unpackBody(job.body)};
    const response=await fetch(job.url,options);
    if(!response.ok){if(response.status>=500)break;throw new Error("Queued request failed: "+response.status);}
    await store("queue","readwrite",s=>s.delete(job.id));
  }}catch(error){console.warn("[offline queue]",error)}
  finally{flushing=false;await notify(navigator.onLine?"saved":"offline");}
}
window.OfflineStore={request,enqueue,flush,pendingCount,cacheSet,cacheGet,notify};
window.addEventListener("online",flush);window.addEventListener("offline",()=>notify("offline"));
document.addEventListener("visibilitychange",()=>{if(!document.hidden)flush()});
flush();
