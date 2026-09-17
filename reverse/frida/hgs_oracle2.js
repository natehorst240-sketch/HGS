/* hgs_oracle2.js — inject DAU replies by properly completing MSComm's
 * overlapped WaitCommEvent (SetEvent on its hEvent) so OnComm fires. */
'use strict';
function imp(n){try{if(typeof Module.getGlobalExportByName==='function'){var p=Module.getGlobalExportByName(n);if(p&&!p.isNull())return p;}}catch(e){}try{var m=Process.getModuleByName('kernel32.dll');return m.findExportByName?m.findExportByName(n):m.getExportByName(n);}catch(e){}return null;}
const comHandles={}; let injectQueue=[]; let t0=Date.now(); function ms(){return Date.now()-t0;}
const SetEvent=new NativeFunction(imp('SetEvent'),'int',['pointer']);
let lastMask=null, lastEvent=null;  // from the pending overlapped WaitCommEvent
function tag(h,w){if(!comHandles[h]){comHandles[h]=w;console.log('['+ms()+'] handle '+h+' '+w);}}
['SetCommState','GetCommState','SetCommTimeouts','PurgeComm','SetupComm','ClearCommError','EscapeCommFunction'].forEach(function(f){var a=imp(f);if(a)Interceptor.attach(a,{onEnter(ar){tag(ar[0].toString(),f);}});});
['CreateFileW','CreateFileA'].forEach(function(f){var a=imp(f);if(!a)return;var wide=f.endsWith('W');Interceptor.attach(a,{onEnter(ar){try{this.p=wide?ar[0].readUtf16String():ar[0].readAnsiString();}catch(e){this.p=null;}},onLeave(rv){if(this.p&&this.p.toUpperCase().indexOf('COM')>=0&&!rv.equals(ptr('-1')))tag(rv.toString(),this.p);}});});
// WaitCommEvent: remember the overlapped mask ptr + hEvent so we can complete it later
const wce=imp('WaitCommEvent');if(wce)Interceptor.attach(wce,{onEnter(a){this.h=a[0].toString();this.mask=a[1];this.ov=a[2];},onLeave(rv){if(!comHandles[this.h])return;lastMask=this.mask;if(this.ov&&!this.ov.isNull()){try{lastEvent=this.ov.add(0x10).readPointer();}catch(e){lastEvent=null;}}}});
// ClearCommError: report bytes waiting
const cce=imp('ClearCommError');if(cce)Interceptor.attach(cce,{onEnter(a){this.h=a[0].toString();this.s=a[2];},onLeave(){if(!comHandles[this.h]||!injectQueue.length)return;try{this.s.add(4).writeU32(injectQueue.length);}catch(e){}}});
// ReadFile: hand over injected bytes
const rd=imp('ReadFile');if(rd)Interceptor.attach(rd,{onEnter(a){this.h=a[0].toString();this.b=a[1];this.n=a[2].toInt32();this.lp=a[3];},onLeave(rv){if(!comHandles[this.h]||!injectQueue.length)return;var n=Math.min(this.n,injectQueue.length);var c=injectQueue.slice(0,n);try{this.b.writeByteArray(c);if(this.lp&&!this.lp.isNull())this.lp.writeU32(n);rv.replace(ptr(1));injectQueue=injectQueue.slice(n);console.log('['+ms()+'] << delivered '+n+' ('+injectQueue.length+' left)');send({ev:'delivered',n:n});}catch(e){}}});
// GetOverlappedResult on the comm handle: report success + mask already set
const gor=imp('GetOverlappedResult');if(gor)Interceptor.attach(gor,{onEnter(a){this.h=a[0].toString();this.lp=a[2];},onLeave(rv){if(!comHandles[this.h])return;/*leave as-is*/}});
// TX observation
const wf=imp('WriteFile');if(wf)Interceptor.attach(wf,{onEnter(a){if(!comHandles[a[0].toString()])return;var n=a[2].toInt32();var by=new Uint8Array(a[1].readByteArray(n));var asc='';for(var i=0;i<by.length;i++)asc+=(by[i]>=32&&by[i]<127)?String.fromCharCode(by[i]):'.';console.log('['+ms()+'] >> '+asc);send({ev:'tx',ascii:asc});}});
rpc.exports={inject(h){var p=h.trim().split(/\s+/).filter(Boolean);injectQueue=injectQueue.concat(p.map(function(x){return parseInt(x,16);}));/* wake MSComm's receive thread */ if(lastMask){try{lastMask.writeU32(1);}catch(e){}} if(lastEvent){try{SetEvent(lastEvent);console.log('['+ms()+'] SetEvent on '+lastEvent+' mask=EV_RXCHAR');}catch(e){console.log('SetEvent err '+e);}} return injectQueue.length;},clear(){injectQueue=[];return 0;}};
console.log('hgs_oracle2 active');
