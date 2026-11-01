# Publicação, atualização e rollback

## Pacote 1.0.0

Obtenha entre-turnos-brasil-v1.0.0.zip, final-manifest.json e SHA256SUMS.txt na release v1.0.0 do GitHub. Verifique o SHA-256 do ZIP com Get-FileHash e compare com SHA256SUMS.txt. O ZIP contém index.html na raiz e todas as pastas necessárias; não é o ZIP de código-fonte gerado automaticamente pelo GitHub.

Na Cloudflare, atualize o Worker existente pelo fluxo Upload and deploy. Extraia o ZIP em uma pasta nova e envie seu conteúdo completo (ou essa pasta, verificando que index.html será a raiz). Preserve _headers, assets, release, context e geo. Não envie apenas index.html nem o diretório de código web/src.

Após publicar, abra a raiz e um link compartilhado em janela privada. Confirme versão 1.0.0 no rodapé, carregamento do mapa, troca de dimensão, seleção de faixa, metodologia e exportação. Confirme /version.json com versão e commit esperados. Essa verificação confirma a implantação, não substitui o aceite de uso já concluído.

## Reproduzir

No checkout da tag v1.0.0: entre em web, execute npm ci, npm test, npm run build, node scripts/stamp-release.mjs e node scripts/package-release.mjs. A pasta dist é o site; artifacts/final-manifest.json registra os hashes dos arquivos originais. O empacotador também produz cópias gzip/Brotli. O servidor local scripts/serve-release.mjs é apenas uma ferramenta de validação.

## Atualizar

Crie uma nova versão sem modificar tags publicadas. Registre mudanças no CHANGELOG, atualize a versão do dashboard, execute os testes/build e gere um novo ZIP com manifesto e checksum. Preserve o pacote anterior. Não substitua dados diferentes sob o mesmo identificador imutável: gere nova release/contexto quando necessário. Publique toda a árvore dist de uma só vez. Não inclua credenciais em código, ZIP, logs ou variáveis VITE_*.

## Recuperar versão anterior

Guarde o pacote da versão atualmente funcional antes de atualizar. Para reverter, publique novamente o pacote completo anterior no mesmo Worker, mantendo juntos HTML, assets e dados. Verifique /version.json, raiz, mapa e filtros em janela privada. Evite misturar arquivos de versões distintas. Depois registre a causa e publique a correção em uma nova versão.

## Escopo operacional

O site é estático e não requer chave de API no navegador. A publicação no GitHub não atualiza automaticamente a Cloudflare: este projeto usa envio manual. Domínio próprio e automação de implantação são melhorias opcionais, não condições de conclusão da 1.0.0.

