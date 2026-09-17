/* hgs_trace.js — inject a reply AND log which comm-referencing sites execute,
 * to localize HGS's receive parser. No ASLR, so absolute VAs are valid. */
'use strict';
function imp(n){try{if(typeof Module.getGlobalExportByName==='function'){var p=Module.getGlobalExportByName(n);if(p&&!p.isNull())return p;}}catch(e){}try{var m=Process.getModuleByName('kernel32.dll');return m.findExportByName?m.findExportByName(n):m.getExportByName(n);}catch(e){}return null;}
const comHandles={}; let injectQueue=[]; let t0=Date.now(); function ms(){return Date.now()-t0;}
function tag(h,w){if(!comHandles[h]){comHandles[h]=w;}}
['SetCommState','GetCommState','SetCommTimeouts','PurgeComm','SetupComm','ClearCommError','EscapeCommFunction'].forEach(function(f){var a=imp(f);if(a)Interceptor.attach(a,{onEnter(ar){tag(ar[0].toString(),f);}});});
['CreateFileW','CreateFileA'].forEach(function(f){var a=imp(f);if(!a)return;var wide=f.endsWith('W');Interceptor.attach(a,{onEnter(ar){try{this.p=wide?ar[0].readUtf16String():ar[0].readAnsiString();}catch(e){this.p=null;}},onLeave(rv){if(this.p&&this.p.toUpperCase().indexOf('COM')>=0&&!rv.equals(ptr('-1')))tag(rv.toString(),this.p);}});});
// injection
const cce=imp('ClearCommError');if(cce)Interceptor.attach(cce,{onEnter(a){this.h=a[0].toString();this.s=a[2];},onLeave(){if(!comHandles[this.h]||!injectQueue.length)return;try{this.s.add(4).writeU32(injectQueue.length);}catch(e){}}});
const wce=imp('WaitCommEvent');if(wce)Interceptor.attach(wce,{onEnter(a){this.h=a[0].toString();this.m=a[1];},onLeave(rv){if(!comHandles[this.h]||!injectQueue.length)return;try{this.m.writeU32(1);}catch(e){}rv.replace(ptr(1));}});
const rd=imp('ReadFile');if(rd)Interceptor.attach(rd,{onEnter(a){this.h=a[0].toString();this.b=a[1];this.n=a[2].toInt32();this.lp=a[3];},onLeave(rv){if(!comHandles[this.h]||!injectQueue.length)return;var n=Math.min(this.n,injectQueue.length);var c=injectQueue.slice(0,n);try{this.b.writeByteArray(c);if(this.lp&&!this.lp.isNull())this.lp.writeU32(n);rv.replace(ptr(1));injectQueue=injectQueue.slice(n);console.log('['+ms()+'] << injected '+n);send({ev:'delivered',n:n});}catch(e){}}});
const wf=imp('WriteFile');if(wf)Interceptor.attach(wf,{onEnter(a){if(!comHandles[a[0].toString()])return;var n=a[2].toInt32();var by=new Uint8Array(a[1].readByteArray(n));var asc='';for(var i=0;i<by.length;i++)asc+=(by[i]>=32&&by[i]<127)?String.fromCharCode(by[i]):'.';console.log('['+ms()+'] >> '+asc);send({ev:'tx',ascii:asc});}});
// trace sites (comm-object referencing addresses)
const SITES=[0x4239bc,0x423c12,0x4240db,0x424e5b,0x425502,0x425c75,0x427261,0x4278d1,0x427905,0x427928,0x427d46,0x427d71,0x43f387,0x44b7e7,0x46ae4c,0x46aefc,0x46b418];
const hitCount={};
SITES.forEach(function(va){try{Interceptor.attach(ptr(va),{onEnter(){hitCount[va]=(hitCount[va]||0)+1;if(hitCount[va]<=3){console.log('['+ms()+'] SITE '+va.toString(16)+' hit#'+hitCount[va]);send({ev:'site',va:va.toString(16),n:hitCount[va]});}}});}catch(e){console.log('site '+va.toString(16)+' hook failed: '+e);}});
rpc.exports={inject(h){var p=h.trim().split(/\s+/).filter(Boolean);injectQueue=injectQueue.concat(p.map(function(x){return parseInt(x,16);}));return injectQueue.length;},clear(){injectQueue=[];return 0;}};
console.log('hgs_trace active ('+SITES.length+' sites hooked)');
