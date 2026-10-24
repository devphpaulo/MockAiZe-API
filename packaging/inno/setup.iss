#define Frontend "setup"
#include "common.iss"

[Files]
; Inno owns only the protected temporary extraction. The bridge owns the
; transactional installation, service, firewall, ACLs and product registration.
Source: "{#RepositoryRoot}\build\payload\*"; DestDir: "{tmp}\payload"; Flags: dontcopy recursesubdirs createallsubdirs

[Code]
#include "bridge.iss"
#include "wizard.iss"
