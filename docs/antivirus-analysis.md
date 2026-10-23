# Detecção do instalador e tamanho dos executáveis

Análise de 23/10/2026. Resultado: **detecção pendente de revisão pelo fabricante**.
Esta inspeção não confirma malware nem permite classificar a detecção como falso positivo.

Atualização funcional: a falha de importação QtCore nos EXEs locais antigos foi
atribuída à coleta da ICU de uma ferramenta auxiliar no PATH. O commit `325830b`
isola a compilação, verifica a origem das DLLs e acrescenta diagnóstico gráfico
dos EXEs ao CI. Isso corrige uma incompatibilidade de empacotamento, sem provar
relação causal com a detecção do antivírus. Os hashes e tamanhos abaixo continuam
identificando a amostra original reportada, não os executáveis recompilados.

## Amostra e procedência

O evento fornecido pelo usuário identifica `HEUR:Trojan.Win32.Generic`, componente
Antivírus de Arquivos, com `explorer.exe` acessando `MockAiZe-API-Setup.exe`.
O evento não informa a regra interna que motivou a classificação. Os relatórios
nativos encontrados no diretório do Kaspersky são bases próprias; não foram
convertidos em um trace legível do mecanismo de detecção. A análise usa o evento
fornecido, logs de compilação, código fonte e inspeção estática do artefato.

O [build original 39901224467](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39901224467)
foi produzido do commit `0e2b64edd499d70b4b15b1aa0fea561d2b1749e7`.
A [inspeção 39902707680](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39902707680)
baixou esse mesmo artefato em um runner descartável, sem executar os EXEs.
O MD5 coincide com o evento do usuário, e o SHA-256 coincide com o log do build:

| Arquivo | Bytes | MD5 | SHA-256 |
|---|---:|---|---|
| MockAiZe-API-Setup.exe | 158639912 | `b429d0b256d29613ccc1d976722e05df` | `9c40c0edb8360ce15f56cab3f69abe4b513c702944b1126484e295bc766fde4e` |
| MockAiZeApiUninstall.exe | 48966938 | `8134ba512c8c2adfc7727212726ab862` | `4a8d6743ca5c8c98aa766ae8e977dad6df530fbdf9cec49abb484c52556d2d90` |

Os três executáveis internos do setup também têm os SHA-256 registrados no build
original. Não apareceu divergência que indique substituição posterior dos arquivos.
Isso confirma identidade, não ausência de malware ou integridade de toda a cadeia
de dependências. Ambos os EXEs distribuídos retornaram `NotSigned`, sem publicador
Authenticode. O [relatório JSON](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39902707680/artifacts/12479144149)
contém hashes, tamanho dos componentes, DLLs importadas e estado das assinaturas.

## Logs e código revisados

O log local `build/windows-build.log` mostra compilação completa, seguida por
`Permission denied` ao validar o setup. Na consulta seguinte, o arquivo não existia.
O log do runner registra build completo e smoke aprovado; esse teste funcional
não é uma análise antimalware.

Os avisos do PyInstaller são principalmente módulos condicionais de outros
sistemas e imports opcionais. Eles não identificam uma família de malware nem
explicam a regra do Kaspersky.

Nos entrypoints e fluxos de instalação revisados não foi encontrado código para
baixar e executar cargas externas, coletar senhas do Windows/navegador, exfiltrar
dados ou desativar antivírus. As alterações encontradas registram o serviço
`MockAiZeApi`, ajustam ACLs para LocalService, criam a regra própria de firewall
quando habilitada e registram o configurador/desinstalador. A exclusão de arquivos
depende das escolhas do usuário e valida destinos protegidos. A chamada HTTP de
saúde é para loopback.

Evidências: `packaging/*_entry.py`, `packaging/*.spec`,
`src/mockaize_api/windows_ops.py`, `src/mockaize_api/windows_service.py`,
`src/mockaize_api/setup_ui.py`, `src/mockaize_api/uninstall.py` e
`src/mockaize_api/uninstall_ui.py`.
Essa revisão é limitada a esses fluxos; não foi uma auditoria exaustiva de todas
as dependências binárias e não valida o ambiente interno do Codex.

## Causa comprovada do tamanho

Configurador, desinstalador e setup usam PyInstaller `onefile`, cada um com seu
próprio Python/Qt. O serviço possui outro runtime em `onedir`. O setup inclui os
dois EXEs gráficos já comprimidos, além do serviço e de seu próprio runtime.

| Componente dentro do setup | Bytes comprimidos no arquivo externo |
|---|---:|
| Configurador já empacotado | 48557562 |
| Desinstalador já empacotado | 48547807 |
| OpenGL de software do Qt do próprio setup | 7642087 |
| Qt6Core do próprio setup | 3701127 |
| Qt6Gui do próprio setup | 4273957 |

Só os dois EXEs aninhados ocupam 97.105.369 bytes, cerca de 61% do setup.
O arquivo externo tem 1.561 entradas e declara 246.769.703 bytes descomprimidos;
o desinstalador tem 845 entradas e 121.783.047 bytes descomprimidos.
Esses números explicam tamanho e duplicação. Não constituem evidência de trojan.

Os três EXEs gráficos combinam `onefile` com `uac_admin=True`.
O [PyInstaller recomenda não conceder administrador ao modo onefile](https://pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works),
por causa da preparação das bibliotecas temporárias. Isso é um problema de desenho
da distribuição que precisa ser corrigido independentemente da detecção. Não foi
demonstrado que seja a causa específica da regra heurística do Kaspersky.

## Alternativa recomendada

Usar **Inno Setup para instalação/desinstalação nativas e um único runtime
compartilhado em Program Files**. O configurador Qt e o serviço podem continuar
em Python, em um bundle `onedir` comum. O PyInstaller documenta o
[compartilhamento de dependências em um único COLLECT](https://pyinstaller.org/en/stable/spec-files.html#multipackaging-with-one-folder-apps).
O setup deve instalar os arquivos no diretório protegido antes de executar o
configurador; o desinstalador nativo não deve carregar outra cópia de Python/Qt.

O contrato funcional a preservar é: parar o serviço, confirmar sua remoção,
perguntar sobre os binários e as pastas, proteger o SQLite de origem e concluir
com OK. Atualização, rollback e cancelamento precisam de testes após a migração.
O suporte de build do Inno Setup já consta na
[imagem oficial Windows do Actions](https://github.com/actions/runner-images/blob/main/images/windows/Windows2025-Readme.md).
A migração ainda não foi implementada; não há medição de um novo instalador.

| Opção | Avaliação |
|---|---|
| Inno Setup + runtime compartilhado | Recomendada: mantém entrega EXE e remove a duplicação de Qt/Python entre aplicativos |
| WiX/MSI com bootstrapper EXE | Viável para distribuição corporativa; maior complexidade para manter o fluxo de limpeza opcional |
| Apenas ZIP com onedir | Remove duplicação, mas altera a experiência de instalação solicitada |
| Trocar apenas PyInstaller por outro compilador | Qt continua necessário; a troca isolada não resolve runtimes duplicados nem garante aprovação do antivírus |

A mudança de empacotamento corrige tamanho e o desenho de execução elevada;
não se deve prometê-la como forma de tornar uma amostra indetectável.
Não se recomenda remover DLLs arbitrariamente para reduzir bytes: isso pode
quebrar renderização, runtime ou compatibilidade em outros computadores.

## Revisão da detecção e assinatura

Para esta amostra, o procedimento oficial é atualizar as bases, consultar o objeto
no portal Kaspersky e solicitar revisão aos analistas, incluindo o evento,
hashes, link do build, finalidade do serviço e este relatório.
Veja [orientação oficial do Kaspersky](https://support.kaspersky.com/kaspersky-for-windows/21.27/troubleshooting/other/1870).
A consulta automatizada ao OpenTIP não ficou acessível neste ambiente; não há
veredito desse portal nem protocolo de atendimento. Nenhum arquivo ou mensagem
foi enviado para análise externa e nenhuma exclusão/proteção foi alterada.

Assinatura Authenticode com certificado de publicador verificável deve fazer
parte de uma release de distribuição; não foi fornecido um certificado para este
projeto. Assinar não comprova ausência de malware e não garante remover alertas.
A [Microsoft documenta que SmartScreen avalia reputação do arquivo e do publicador](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).
A imagem fornecida mostra o serviço SmartScreen indisponível e editor desconhecido;
isso é diferente do evento de detecção do Kaspersky e não é um laudo de malware.

Conclusão operacional: não liberar esta amostra como instalador homologado até
esclarecer a detecção. O sucesso dos testes e da inspeção estática não substitui
o parecer do antivírus nem a homologação privilegiada em VM.
