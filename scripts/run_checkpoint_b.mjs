/** Dedicated disposable emulator; never reset the owner's 9399 database. */
import { cpSync, mkdirSync, writeFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { createConnection } from 'node:net';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root=dirname(dirname(fileURLToPath(import.meta.url)));
const occupied=await new Promise(resolve=>{
 const socket=createConnection({host:'127.0.0.1',port:9499});
 socket.once('connect',()=>{socket.destroy();resolve(true);});
 socket.once('error',()=>resolve(false));
});
if(occupied){process.stderr.write('Port 9499 is already in use. Stop the isolated test/preview emulator before running this suite. The owner database at 9399 will not be touched.\n');process.exit(1);}
const target=join(root,'.local','checkpoint-b-tests');mkdirSync(target,{recursive:true});
cpSync(join(root,'dataconnect'),join(target,'dataconnect'),{recursive:true});
const config=join(target,'firebase.json');
writeFileSync(config,JSON.stringify({dataconnect:{source:'dataconnect'},emulators:{dataconnect:{host:'127.0.0.1',port:9499},ui:{enabled:false},singleProjectMode:true}}));
const child=spawn(process.execPath,[join(root,'node_modules','firebase-tools','lib','bin','firebase.js'),'emulators:exec','--only','dataconnect','--project','demo-terra-local','--config',config,'node scripts/run_python.mjs scripts/run_checkpoint_b_tests.py'],{cwd:root,stdio:'inherit',env:{...process.env,TERRA_LLM_ENABLED:'false',TERRA_AUTOMATCH_ENABLED:'0'}});
child.on('error',error=>{process.stderr.write(error.message+'\n');process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code??1;});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
