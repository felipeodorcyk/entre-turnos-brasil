import {readFileSync,writeFileSync,copyFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
const pkg=JSON.parse(readFileSync('package.json','utf8'));
const version={version:pkg.version,commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),dataRelease:JSON.parse(readFileSync('public/release/current.json','utf8'))};
writeFileSync('dist/version.json',JSON.stringify(version,null,2)+'\n');
copyFileSync('../LICENSE','dist/LICENSE.txt');
copyFileSync('../docs/FONTES_E_ATRIBUICOES.md','dist/FONTES_E_ATRIBUICOES.md');
console.log('Stamped',version.version,version.commit);
