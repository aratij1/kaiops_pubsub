# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: discovery-layout.spec.js >> discovery is a first-class responsive alert view
- Location: tests/e2e/discovery-layout.spec.js:3:1

# Error details

```
Error: ENOMEM: not enough memory, write
```

# Page snapshot

```yaml
- main [ref=e3]:
  - link "Skip to workspace content" [ref=e4] [cursor=pointer]:
    - /url: "#workspace-content"
  - generic [ref=e5]:
    - complementary [ref=e6]:
      - generic [ref=e7]:
        - paragraph [ref=e8]: KaiOps
        - heading "Operations" [level=2] [ref=e9]
        - paragraph [ref=e10]: Monitor, investigate, and resolve.
      - generic [ref=e11]:
        - heading "Monitor" [level=3] [ref=e12]
        - generic [ref=e13]:
          - text: Application
          - combobox "Application" [ref=e14]:
            - option "KaiOps" [selected]
            - option "Telemetry"
            - option "Real Use Cases"
            - option "Test Use Cases"
        - generic [ref=e15]: api-gateway is ok
      - group [ref=e17]:
        - generic "Display preferences +" [ref=e18] [cursor=pointer]
      - navigation "Primary navigation" [ref=e19]:
        - generic [ref=e21]:
          - generic [ref=e22]:
            - heading "Operations" [level=3] [ref=e23]
            - generic [ref=e24]:
              - button "Dashboard" [ref=e25] [cursor=pointer]:
                - img [ref=e27]
                - generic [ref=e31]: Dashboard
              - button "Live Alerts" [ref=e32] [cursor=pointer]:
                - img [ref=e34]
                - generic [ref=e41]: Live Alerts
              - button "Incidents" [ref=e42] [cursor=pointer]:
                - img [ref=e44]
                - generic [ref=e49]: Incidents
              - button "Approvals" [ref=e50] [cursor=pointer]:
                - img [ref=e52]
                - generic [ref=e55]: Approvals
          - generic [ref=e56]:
            - heading "Intelligence" [level=3] [ref=e57]
            - generic [ref=e58]:
              - button "Copilot" [ref=e59] [cursor=pointer]:
                - img [ref=e61]
                - generic [ref=e64]: Copilot
              - button "Agent Flow" [ref=e65] [cursor=pointer]:
                - img [ref=e67]
                - generic [ref=e71]: Agent Flow
              - button "Knowledge" [ref=e72] [cursor=pointer]:
                - img [ref=e74]
                - generic [ref=e76]: Knowledge
          - generic [ref=e77]:
            - heading "Governance" [level=3] [ref=e78]
            - generic [ref=e79]:
              - button "Gateway Safety" [ref=e80] [cursor=pointer]:
                - img [ref=e82]
                - generic [ref=e85]: Gateway Safety
              - button "Audit" [ref=e86] [cursor=pointer]:
                - img [ref=e88]
                - generic [ref=e91]: Audit
              - button "Closed Incidents" [ref=e92] [cursor=pointer]:
                - img [ref=e94]
                - generic [ref=e97]: Closed Incidents
          - generic [ref=e98]:
            - heading "Platform" [level=3] [ref=e99]
            - generic [ref=e100]:
              - button "Applications" [ref=e101] [cursor=pointer]:
                - img [ref=e103]
                - generic [ref=e113]: Applications
              - button "Integrations" [ref=e114] [cursor=pointer]:
                - img [ref=e116]
                - generic [ref=e122]: Integrations
              - button "Admin" [ref=e123] [cursor=pointer]:
                - img [ref=e125]
                - generic [ref=e128]: Admin
      - generic [ref=e129]:
        - button "Refresh" [ref=e130] [cursor=pointer]
        - button "Health" [ref=e131] [cursor=pointer]
    - generic [ref=e132]:
      - generic [ref=e133]:
        - paragraph [ref=e134]: Operations
        - heading "Operational Workspace" [level=1] [ref=e135]
        - paragraph [ref=e136]: home · health · attention
        - navigation "Breadcrumb" [ref=e137]:
          - list [ref=e138]:
            - listitem [ref=e139]: Operations
            - listitem [ref=e140]: /Dashboard
        - generic [ref=e141]:
          - generic [ref=e142]: api-gateway is ok
          - generic [ref=e144]: "Monitoring: KaiOps"
          - generic [ref=e145]: "Signed in: admin (Administrator)"
          - button "Logout" [ref=e146] [cursor=pointer]
      - group "Global operational capabilities" [ref=e147]:
        - generic "Search & personal work Find records, assignments, and notifications ⌄" [ref=e148] [cursor=pointer]:
          - generic [ref=e149]: Search & personal work
          - generic [ref=e150]: Find records, assignments, and notifications
          - text: ⌄
        - generic [ref=e151]:
          - tablist "Global operations" [ref=e152]:
            - tab "Search" [selected] [ref=e153] [cursor=pointer]
            - tab "My Work (0)" [ref=e154] [cursor=pointer]
            - tab "Notifications (2)" [ref=e155] [cursor=pointer]
          - generic [ref=e156]:
            - generic [ref=e157]:
              - generic [ref=e158]: Global search
              - searchbox "Global search" [active] [ref=e159]
            - paragraph [ref=e160]: Searches currently loaded, role-authorized operational records.
      - generic [ref=e161]:
        - article [ref=e162]:
          - generic [ref=e163]:
            - generic [ref=e164]:
              - generic [ref=e165]: Administrator dashboard
              - heading "Platform attention" [level=2] [ref=e166]
              - paragraph [ref=e167]: Connector, queue, agent, workflow, and telemetry health.
            - generic [ref=e168]:
              - generic [ref=e169]: Current operational window
              - strong [ref=e170]: Asia/Kolkata (IST)
              - generic [ref=e171]: current data
          - generic [ref=e172]:
            - article [ref=e173]:
              - generic [ref=e174]: Connector Health
              - strong [ref=e175]: 2/2
              - paragraph [ref=e176]: Registered monitoring applications without a failed health status.
              - button "View records" [ref=e177] [cursor=pointer]
            - article [ref=e178]:
              - generic [ref=e179]: Queue Health
              - strong [ref=e180]: Unknown
              - paragraph [ref=e181]: Configured deployment message-bus provider; queue age is unavailable in this UI contract.
              - button "View records" [ref=e182] [cursor=pointer]
            - article [ref=e183]:
              - generic [ref=e184]: Agent Health
              - strong [ref=e185]: "0"
              - paragraph [ref=e186]: Persisted agent or trace events for the selected alert.
              - button "View records" [ref=e187] [cursor=pointer]
            - article [ref=e188]:
              - generic [ref=e189]: Workflow Health
              - strong [ref=e190]: Clear
              - paragraph [ref=e191]: Selected workflow events containing failed or error state.
              - button "View records" [ref=e192] [cursor=pointer]
            - article [ref=e193]:
              - generic [ref=e194]: Telemetry
              - strong [ref=e195]: "0"
              - paragraph [ref=e196]: API gateway telemetry events in the current loaded window.
              - button "View records" [ref=e197] [cursor=pointer]
          - group [ref=e198]:
            - generic "Metric definitions and data quality" [ref=e199] [cursor=pointer]
        - article [ref=e200]:
          - generic [ref=e201]:
            - generic [ref=e202]:
              - text: Monitoring projects
              - heading "KaiOps + Telemetry" [level=2] [ref=e203]
              - paragraph [ref=e204]: Select a project to scope alerts, incidents, discovery evidence, and timeline events.
            - button "Refresh Projects" [ref=e205] [cursor=pointer]
          - generic [ref=e206]:
            - button "KO KaiOps kaiops namespace http://api-gateway:8000/metrics dashboard_created" [ref=e207] [cursor=pointer]:
              - generic [ref=e208]: KO
              - generic [ref=e209]:
                - strong [ref=e210]: KaiOps
                - generic [ref=e211]: kaiops namespace
                - code [ref=e212]: http://api-gateway:8000/metrics
              - generic [ref=e213]: dashboard_created
            - button "OT Telemetry telemetry namespace http://host.docker.internal:19090/metrics dashboard_created" [ref=e214] [cursor=pointer]:
              - generic [ref=e215]: OT
              - generic [ref=e216]:
                - strong [ref=e217]: Telemetry
                - generic [ref=e218]: telemetry namespace
                - code [ref=e219]: http://host.docker.internal:19090/metrics
              - generic [ref=e220]: dashboard_created
        - article [ref=e221]:
          - heading "Workflow Health & Next Action" [level=2] [ref=e223]
          - paragraph [ref=e224]: Fast status across intake, resolution, approval, and remediation.
          - generic [ref=e225]:
            - generic [ref=e226]:
              - strong [ref=e227]: Alert Intake
              - generic [ref=e228]: ACTIVE
              - paragraph [ref=e229]: 2 open alerts ready for triage.
            - generic [ref=e230]:
              - strong [ref=e231]: Approval Queue
              - generic [ref=e232]: CLEAR
              - paragraph [ref=e233]: No incidents are waiting for human approval.
            - generic [ref=e234]:
              - strong [ref=e235]: Resolution Intelligence
              - generic [ref=e236]: ATTENTION
              - paragraph [ref=e237]: No resolution trace detected for selected alert yet.
            - generic [ref=e238]:
              - strong [ref=e239]: Remediation Automation
              - generic [ref=e240]: ATTENTION
              - paragraph [ref=e241]: No remediation execution trace detected yet.
          - paragraph [ref=e242]: "Recommended next step: Inspect Cockpit and review Evidence or Timeline for Resolution Intelligence output."
        - article [ref=e243]:
          - generic [ref=e244]:
            - heading "Alert Stream" [level=2] [ref=e245]
            - generic [ref=e246]:
              - text: Show
              - combobox "Show alerts" [ref=e247]:
                - option "25" [selected]
                - option "50"
                - option "100"
                - option "200"
              - text: alerts
            - button "Refresh" [ref=e248] [cursor=pointer]
          - generic [ref=e249]:
            - group "Alert triage focus" [ref=e250]:
              - button "Ops 2" [ref=e251] [cursor=pointer]
              - button "All 2" [ref=e252] [cursor=pointer]
              - button "Critical 1" [ref=e253] [cursor=pointer]
              - button "High 1" [ref=e254] [cursor=pointer]
              - button "Awaiting 0" [ref=e255] [cursor=pointer]
              - button "Active 0" [ref=e256] [cursor=pointer]
              - button "Closed 0" [ref=e257] [cursor=pointer]
              - button "Test 0" [ref=e258] [cursor=pointer]
            - textbox "Search alert name, service, app, id" [ref=e260]
          - paragraph [ref=e261]: Showing 2 of 2 alerts for KaiOps.
          - group "Filter dashboard alerts by source" [ref=e262]:
            - button "All 2" [pressed] [ref=e263] [cursor=pointer]
            - button "Prometheus 0" [ref=e264] [cursor=pointer]
            - button "Telemetry 0" [ref=e265] [cursor=pointer]
            - button "Email 1" [ref=e266] [cursor=pointer]
            - button "Ticket 0" [ref=e267] [cursor=pointer]
            - button "Logs 1" [ref=e268] [cursor=pointer]
          - paragraph [ref=e269]: L2/L3/Admin can set future severity overrides by alert name + service + environment.
          - region "Alert stream table" [ref=e270]:
            - table [ref=e271]:
              - rowgroup [ref=e272]:
                - row "Alert ID Time (UTC) Name Rule Application Service Source Severity Tier Status Action" [ref=e273]:
                  - columnheader "Alert ID" [ref=e274]
                  - columnheader "Time (UTC)" [ref=e275]
                  - columnheader "Name" [ref=e276]
                  - columnheader "Rule" [ref=e277]
                  - columnheader "Application" [ref=e278]
                  - columnheader "Service" [ref=e279]
                  - columnheader "Source" [ref=e280]
                  - columnheader "Severity" [ref=e281]
                  - columnheader "Tier" [ref=e282]
                  - columnheader "Status" [ref=e283]
                  - columnheader "Action" [ref=e284]
              - rowgroup [ref=e285]:
                - button "Open alert 11111111-1111-4111-8111-111111111111" [ref=e286] [cursor=pointer]:
                  - cell "11111111...111111" [ref=e287]
                  - cell "-" [ref=e288]
                  - cell "Pod crash loop" [ref=e289]
                  - cell "Pod crash loop" [ref=e290]
                  - cell "kaiops-core1" [ref=e291]
                  - cell "user-profile" [ref=e292]
                  - cell "Email" [ref=e293]:
                    - generic [ref=e295]: Email
                  - cell "CRITICAL" [ref=e296]:
                    - generic [ref=e297]: CRITICAL
                  - cell "-" [ref=e298]:
                    - generic [ref=e299]: "-"
                  - cell "active" [ref=e300]:
                    - generic [ref=e301]: active
                  - cell "Inspect" [ref=e302]:
                    - button "Inspect" [ref=e303]
                - button "Open alert alert-log-1" [ref=e304] [cursor=pointer]:
                  - cell "alert-log-1" [ref=e305]
                  - cell "-" [ref=e306]
                  - cell "Checkout log error burst" [ref=e307]
                  - cell "Checkout log error burst" [ref=e308]
                  - cell "KaiOps" [ref=e309]
                  - cell "checkout-api" [ref=e310]
                  - cell "Logs / OpenSearch" [ref=e311]:
                    - generic [ref=e313]: Logs / OpenSearch
                  - cell "HIGH" [ref=e314]:
                    - generic [ref=e315]: HIGH
                  - cell "-" [ref=e316]:
                    - generic [ref=e317]: "-"
                  - cell "active" [ref=e318]:
                    - generic [ref=e319]: active
                  - cell "Inspect" [ref=e320]:
                    - button "Inspect" [ref=e321]
        - article [ref=e322]:
          - generic [ref=e323]:
            - generic [ref=e324]:
              - text: Guided Incident Cockpit
              - heading "Pod crash loop" [level=2] [ref=e325]
              - paragraph [ref=e326]: No concise incident summary was supplied.
            - generic [ref=e327]:
              - generic [ref=e328]: CRITICAL
              - generic [ref=e329]: investigating
          - generic [ref=e330]:
            - generic [ref=e331]:
              - generic [ref=e332]: Service
              - strong [ref=e333]: user-profile
            - generic [ref=e334]:
              - generic [ref=e335]: Environment
              - strong [ref=e336]: production
            - generic [ref=e337]:
              - generic [ref=e338]: Evidence
              - strong [ref=e339]: 0 linked
            - generic [ref=e340]:
              - generic [ref=e341]: Grounding
              - strong [ref=e342]: 0%
          - region "Evidence" [ref=e343]:
            - generic [ref=e344]:
              - text: Recommended next step
              - heading "Evidence" [level=3] [ref=e345]
              - paragraph [ref=e346]: 0 linked record(s). KaiOps will keep your selected incident and context in view.
            - button "Continue to Evidence" [ref=e347] [cursor=pointer]
          - navigation "Incident progress" [ref=e348]:
            - button "✓ Orient" [ref=e349] [cursor=pointer]:
              - generic [ref=e350]: ✓
              - strong [ref=e351]: Orient
            - button "02 Evidence" [ref=e352] [cursor=pointer]:
              - generic [ref=e353]: "02"
              - strong [ref=e354]: Evidence
            - button "✓ Understand" [ref=e355] [cursor=pointer]:
              - generic [ref=e356]: ✓
              - strong [ref=e357]: Understand
            - button "✓ Plan" [ref=e358] [cursor=pointer]:
              - generic [ref=e359]: ✓
              - strong [ref=e360]: Plan
            - button "05 Decide" [ref=e361] [cursor=pointer]:
              - generic [ref=e362]: "05"
              - strong [ref=e363]: Decide
            - button "06 Execute" [ref=e364] [cursor=pointer]:
              - generic [ref=e365]: "06"
              - strong [ref=e366]: Execute
            - button "07 Validate" [ref=e367] [cursor=pointer]:
              - generic [ref=e368]: "07"
              - strong [ref=e369]: Validate
          - group [ref=e370]:
            - generic "Rule context and severity controls" [ref=e371]
            - option "info"
            - option "warning"
            - option "high"
            - option "critical" [selected]
        - article [ref=e372]:
          - generic [ref=e373]:
            - generic [ref=e374]:
              - text: Active incident workspace
              - heading "Alert Details Cockpit" [level=2] [ref=e375]
              - 'heading "user-profile: Pod crash loop" [level=3] [ref=e376]'
              - paragraph [ref=e377]:
                - text: "Current task:"
                - strong [ref=e378]: Orient
                - text: ". Recommended next:"
                - strong [ref=e379]: Evidence
                - text: .
            - generic "Incident record navigation" [ref=e380]:
              - button "Previous" [disabled] [ref=e381]
              - generic [ref=e382]: 1 of 2
              - button "Next" [ref=e383] [cursor=pointer]
          - generic [ref=e384]:
            - generic [ref=e385]:
              - strong [ref=e386]: "ID:"
              - text: 11111111-1111-4111-8111-111111111111
            - generic [ref=e387]:
              - strong [ref=e388]: "Service:"
              - text: user-profile
            - generic [ref=e389]:
              - strong [ref=e390]: "Severity:"
              - text: CRITICAL
            - generic [ref=e391]:
              - strong [ref=e392]: "Status:"
              - generic [ref=e393]: investigating
          - article [ref=e394]:
            - heading "Decision Gate" [level=3] [ref=e396]
            - paragraph [ref=e397]: Incident is investigating; no active pending approval is linked.
            - table [ref=e399]:
              - rowgroup [ref=e400]:
                - row "Incident incident-discovery-1" [ref=e401]:
                  - rowheader "Incident" [ref=e402]
                  - cell "incident-discovery-1" [ref=e403]
                - row "Incident Status investigating" [ref=e404]:
                  - rowheader "Incident Status" [ref=e405]
                  - cell "investigating" [ref=e406]:
                    - generic [ref=e407]: investigating
                - row "Approval Status not active" [ref=e408]:
                  - rowheader "Approval Status" [ref=e409]
                  - cell "not active" [ref=e410]
                - row "Role Eligible yes" [ref=e411]:
                  - rowheader "Role Eligible" [ref=e412]
                  - cell "yes" [ref=e413]
          - tablist "Incident workspace sections" [ref=e414]:
            - tab "Overview" [selected] [ref=e415] [cursor=pointer]:
              - generic [ref=e416]: ✓
              - strong [ref=e417]: Orient
              - generic [ref=e418]: Identity and lifecycle
            - tab "Evidence" [ref=e419] [cursor=pointer]:
              - generic [ref=e420]: "02"
              - strong [ref=e421]: Evidence
              - generic [ref=e422]: 0 linked record(s)
            - tab "RCA & Impact" [ref=e423] [cursor=pointer]:
              - generic [ref=e424]: ✓
              - strong [ref=e425]: Understand
              - generic [ref=e426]: RCA and impact
            - tab "Resolution" [ref=e427] [cursor=pointer]:
              - generic [ref=e428]: ✓
              - strong [ref=e429]: Plan
              - generic [ref=e430]: Recommended response
            - tab "Approval" [ref=e431] [cursor=pointer]:
              - generic [ref=e432]: "05"
              - strong [ref=e433]: Decide
              - generic [ref=e434]: pending
            - tab "Execution" [ref=e435] [cursor=pointer]:
              - generic [ref=e436]: "06"
              - strong [ref=e437]: Execute
              - generic [ref=e438]: not started
            - tab "Audit Trail" [ref=e439] [cursor=pointer]:
              - generic [ref=e440]: "07"
              - strong [ref=e441]: Validate
              - generic [ref=e442]: audit and recovery
          - generic [ref=e443]:
            - button "Reload Alert Details" [ref=e444] [cursor=pointer]
            - button "Regenerate RCA For This Alert" [ref=e445] [cursor=pointer]
          - generic [ref=e446]:
            - generic [ref=e447]:
              - text: Unified response cockpit
              - heading "Incident Workspace" [level=3] [ref=e448]
              - paragraph [ref=e449]: Follow the incident, verify the evidence, make the decision, and execute recovery without switching tabs.
            - generic [ref=e450]:
              - generic [ref=e451]:
                - strong [ref=e452]: investigating
                - text: lifecycle
              - generic [ref=e453]:
                - strong [ref=e454]: "19"
                - text: events
              - generic [ref=e455]:
                - strong [ref=e456]: "0"
                - text: documents
              - generic [ref=e457]:
                - strong [ref=e458]: 0%
                - text: grounded
          - group [ref=e459]:
            - generic "01 Incident Overview Alert identity, status, root cause, quality metrics, and stage completeness. Hide" [ref=e460] [cursor=pointer]:
              - generic [ref=e461]:
                - generic [ref=e462]: "01"
                - heading "Incident Overview" [level=3] [ref=e463]
                - paragraph [ref=e464]: Alert identity, status, root cause, quality metrics, and stage completeness.
              - generic [ref=e465]: Hide
            - table [ref=e467]:
              - rowgroup [ref=e468]:
                - row "Alert Pod crash loop" [ref=e469]:
                  - rowheader "Alert" [ref=e470]
                  - cell "Pod crash loop" [ref=e471]
                - row "Details Source Canonical processed workflow result; Discovery and Resolution LLM outputs are shown when available." [ref=e472]:
                  - rowheader "Details Source" [ref=e473]
                  - cell "Canonical processed workflow result; Discovery and Resolution LLM outputs are shown when available." [ref=e474]
                - row "Incident incident-discovery-1" [ref=e475]:
                  - rowheader "Incident" [ref=e476]
                  - cell "incident-discovery-1" [ref=e477]
                - row "Persisted Incident Status investigating" [ref=e478]:
                  - rowheader "Persisted Incident Status" [ref=e479]
                  - cell "investigating" [ref=e480]:
                    - generic [ref=e481]: investigating
                - row "Closed At -" [ref=e482]:
                  - rowheader "Closed At" [ref=e483]
                  - cell "-" [ref=e484]
                - row "Service user-profile" [ref=e485]:
                  - rowheader "Service" [ref=e486]
                  - cell "user-profile" [ref=e487]
                - row "Analysis Status resolved-analysis" [ref=e488]:
                  - rowheader "Analysis Status" [ref=e489]
                  - cell "resolved-analysis" [ref=e490]
                - row "Root Cause Memory pressure in user-profile" [ref=e491]:
                  - rowheader "Root Cause" [ref=e492]
                  - cell "Memory pressure in user-profile" [ref=e493]
                - row "Recommended Action Restart the affected pod after approval and validate memory." [ref=e494]:
                  - rowheader "Recommended Action" [ref=e495]
                  - cell "Restart the affected pod after approval and validate memory." [ref=e496]
                - row "Impact Intermittent profile failures" [ref=e497]:
                  - rowheader "Impact" [ref=e498]
                  - cell "Intermittent profile failures" [ref=e499]
                - row "External Knowledge not required" [ref=e500]:
                  - rowheader "External Knowledge" [ref=e501]
                  - cell "not required" [ref=e502]
            - heading "AI Evaluation Metrics" [level=3] [ref=e503]
            - generic [ref=e504]:
              - article [ref=e505]:
                - generic [ref=e506]: Overall Quality
                - strong [ref=e507]: 25%
                - generic [ref=e508]: low | ui-derived-quality-gate
              - article [ref=e509]:
                - generic [ref=e510]: Confidence
                - strong [ref=e511]: 72%
                - generic [ref=e512]: Recommendation certainty
              - article [ref=e513]:
                - generic [ref=e514]: Grounding
                - strong [ref=e515]: 0%
                - generic [ref=e516]: Evidence and context support
              - article [ref=e517]:
                - generic [ref=e518]: Hallucination Risk
                - strong [ref=e519]: 82%
                - generic [ref=e520]: review recommended
              - article [ref=e521]:
                - generic [ref=e522]: Citation Coverage
                - strong [ref=e523]: 0%
                - generic [ref=e524]: "- citation(s)"
              - article [ref=e525]:
                - generic [ref=e526]: Evidence Coverage
                - strong [ref=e527]: 0%
                - generic [ref=e528]: 0 RAG match(es)
            - heading "Persisted Stage Completeness" [level=3] [ref=e529]
            - table [ref=e531]:
              - rowgroup [ref=e532]:
                - row "Stage Persisted Matched Event Types" [ref=e533]:
                  - columnheader "Stage" [ref=e534]
                  - columnheader "Persisted" [ref=e535]
                  - columnheader "Matched Event Types" [ref=e536]
              - rowgroup [ref=e537]:
                - row "No persisted stage rows found for incident." [ref=e538]:
                  - cell "No persisted stage rows found for incident." [ref=e539]
            - paragraph [ref=e540]: "Completion: 0/0 (0%)"
```

# Test source

```ts
  52  |   };
  53  | 
  54  |   let sawLandingPadRequest = false;
  55  |   let sawArchivedLandingPadRequest = false;
  56  |   let alertsAllRequestCount = 0;
  57  |   await page.route("**/api-gateway/**", async (route) => {
  58  |     const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
  59  |     const body = path === "/auth/login"
  60  |       ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
  61  |       : path === "/healthz"
  62  |         ? { status: "ok", service: "api-gateway" }
  63  |           : path.endsWith("/processed-result")
  64  |             ? { data: { workflow } }
  65  |           : path.startsWith("/evaluations/by-recommendation/")
  66  |             ? { data: { updated: true } }
  67  |           : path.startsWith("/alerts/all")
  68  |           ? (() => {
  69  |             alertsAllRequestCount += 1;
  70  |             return { data: { rows: [
  71  |               { alert_id: "11111111-1111-4111-8111-111111111111", id: "11111111-1111-4111-8111-111111111111", name: "Pod crash loop", service: "user-profile", application: "kaiops-core1", environment: "production", labels: { project_name: "KaiOps", alert_fingerprint: "email-pod-crash-1", environment: "production" }, severity: "critical", status: "active", source: "email" },
  72  |               { alert_id: "alert-log-1", id: "alert-log-1", name: "Checkout log error burst", service: "checkout-api", application: "KaiOps", labels: { project_name: "KaiOps", origin_system: "opensearch", ingestion_channel: "log" }, severity: "high", status: "active", source: "opensearch-log-alert" },
  73  |               { alert_id: "alert-telemetry-1", id: "alert-telemetry-1", name: "Telemetry signals missing", service: "astronomy-shop", application: "Telemetry", labels: { project_name: "Telemetry", origin_system: "telemetry", ingestion_channel: "monitoring" }, severity: "warning", status: "active", source: "telemetry" },
  74  |             ] } };
  75  |           })()
  76  |           : path === "/applications"
  77  |             ? { data: { rows: [
  78  |                 { id: "project-kaiops", name: "KaiOps", namespace: "kaiops", status: "dashboard_created", metrics_endpoint: "http://api-gateway:8000/metrics" },
  79  |                 { id: "project-telemetry", name: "Telemetry", namespace: "telemetry", status: "dashboard_created", metrics_endpoint: "http://host.docker.internal:19090/metrics" },
  80  |               ] } }
  81  |             : path.startsWith("/landing-pad/recent")
  82  |               ? (() => {
  83  |                 sawLandingPadRequest = true;
  84  |                 if (new URL(route.request().url()).searchParams.get("include_archive") === "true") {
  85  |                   sawArchivedLandingPadRequest = true;
  86  |                 }
  87  |                 return { data: { rows: [
  88  |                   {
  89  |                     file: "checkout-log-alert.json",
  90  |                     received_at: "2026-07-25T12:00:00Z",
  91  |                     status: "processed",
  92  |                     source: "opensearch-log-alert",
  93  |                     name: "Checkout log error burst",
  94  |                     service: "checkout-api",
  95  |                     application: "KaiOps",
  96  |                     project_name: "KaiOps",
  97  |                     severity: "high",
  98  |                     labels: { project_name: "KaiOps", origin_system: "opensearch", ingestion_channel: "log" },
  99  |                   },
  100 |                   {
  101 |                     file: "email-pod-crash-duplicate.eml",
  102 |                     received_at: "2026-07-25T12:01:00Z",
  103 |                     status: "processed",
  104 |                     source: "email",
  105 |                     name: "Pod crash loop",
  106 |                     service: "user-profile",
  107 |                     application: "KaiOps",
  108 |                     project_name: "KaiOps",
  109 |                     severity: "critical",
  110 |                     labels: { project_name: "KaiOps", origin_system: "email", ingestion_channel: "email", alert_fingerprint: "email-pod-crash-1" },
  111 |                   },
  112 |                   {
  113 |                     file: "jira-resolved.json",
  114 |                     received_at: "2026-07-25T12:02:00Z",
  115 |                     status: "processed",
  116 |                     alert_status: "inactive",
  117 |                     source: "jira",
  118 |                     name: "Checkout incident resolved",
  119 |                     service: "checkout-api",
  120 |                     application: "KaiOps",
  121 |                     severity: "info",
  122 |                     labels: { project_name: "KaiOps", origin_system: "jira", ingestion_channel: "ticket", alert_status: "inactive" },
  123 |                   },
  124 |                 ] } };
  125 |               })()
  126 |             : { data: [], rows: [], summary: {}, items: [] };
  127 |     await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  128 |   });
  129 |   await page.route("**/monitoring-adapter/**", async (route) => {
  130 |     await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { workflow } }) });
  131 |   });
  132 |   await page.goto("/");
  133 |   await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  134 |   await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  135 |   await page.getByRole("button", { name: "Sign In" }).click();
  136 | 
  137 |   await expect(page.getByRole("heading", { name: "KaiOps + Telemetry" })).toBeVisible();
  138 |   await expect(page.getByText("Administrator dashboard", { exact: true })).toBeVisible();
  139 |   await expect(page.getByRole("heading", { name: "Platform attention", exact: true })).toBeVisible();
  140 |   const globalOperations = page.getByLabel("Global operational capabilities");
  141 |   await globalOperations.getByRole("searchbox", { name: "Global search" }).fill("Pod crash");
  142 |   await expect(globalOperations.getByRole("list", { name: "Global search results" })).toContainText("Alert: Pod crash loop");
  143 |   await globalOperations.getByRole("tab", { name: /My Work/ }).click();
  144 |   await expect(globalOperations.getByText("Collaboration unavailable", { exact: true })).toBeVisible();
  145 |   await expect(globalOperations.getByRole("button", { name: "Add note / watcher unavailable" })).toBeDisabled();
  146 |   await globalOperations.getByRole("tab", { name: /Notifications/ }).click();
  147 |   await expect(globalOperations.getByText("Delivery preferences unavailable", { exact: true })).toBeVisible();
  148 |   await expect(globalOperations.getByRole("button", { name: "Configure delivery unavailable" })).toBeDisabled();
  149 |   await globalOperations.screenshot({ path: "artifacts/phase10-global-operations.png" });
  150 |   await globalOperations.getByRole("tab", { name: "Search", exact: true }).click();
  151 |   await globalOperations.getByRole("searchbox", { name: "Global search" }).fill("");
> 152 |   await page.screenshot({ path: "artifacts/phase6-administrator-dashboard.png", fullPage: true });
      |   ^ Error: ENOMEM: not enough memory, write
  153 |   await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Operations");
  154 |   await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Intelligence");
  155 |   await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Governance");
  156 |   await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Platform");
  157 |   await page.screenshot({ path: "artifacts/phase4-authoritative-navigation.png", fullPage: true });
  158 |   await page.getByRole("button", { name: "Live Alerts", exact: true }).click();
  159 |   await expect(page).toHaveURL(/\/alerts$/);
  160 |   await expect(page.getByRole("heading", { name: "Alert Ingestion Stream", exact: true })).toBeVisible();
  161 |   await expect.poll(() => sawLandingPadRequest).toBe(true);
  162 |   expect(sawArchivedLandingPadRequest).toBe(false);
  163 |   await expect(page.getByRole("button", { name: /Email/ })).toBeVisible();
  164 |   await expect(page.getByRole("button", { name: /Logs \/ OpenSearch/ })).toBeVisible();
  165 |   await expect(page.getByRole("button", { name: /Prometheus/ })).toBeVisible();
  166 |   await expect(page.getByRole("button", { name: /Tickets \/ Jira/ })).toBeVisible();
  167 |   await expect(page.getByRole("tablist", { name: "Alert lifecycle sections" }).getByRole("tab")).toHaveCount(4);
  168 |   await expect(page.getByLabel("Saved view").locator("option")).toHaveCount(5);
  169 |   await expect(page.getByText(/Updated exactly:/)).toBeVisible();
  170 |   await page.getByRole("button", { name: "Pause live" }).click();
  171 |   await expect(page.getByText("Live updates paused", { exact: true })).toBeVisible();
  172 |   await page.getByRole("button", { name: "Resume live" }).click();
  173 |   await expect(page.locator(".ingestion-event.channel-email").filter({ hasText: "Pod crash loop" }).first()).toBeVisible();
  174 |   await expect(page.getByText("Checkout log error burst", { exact: true }).first()).toBeVisible();
  175 |   await expect(page.locator(".ingestion-event.channel-email").filter({ hasText: "Occurrences" }).first()).toBeVisible();
  176 |   await page.screenshot({ path: "artifacts/phase7-alert-ingestion-controls.png", fullPage: true });
  177 |   await page.getByRole("tab", { name: "Resolved" }).click();
  178 |   await page.getByRole("button", { name: /Tickets \/ Jira/ }).click();
  179 |   await expect(page.getByText("Checkout incident resolved", { exact: true })).toBeVisible();
  180 |   await expect(page.locator(".ingestion-event").filter({ hasText: "inactive" })).toBeVisible();
  181 |   await page.getByTitle("Dashboard", { exact: true }).click();
  182 |   await expect(page).toHaveURL(/\/$/);
  183 |   await expect(page.getByRole("heading", { name: "KaiOps + Telemetry" })).toBeVisible();
  184 |   await expect(page.getByText("Pod crash loop", { exact: true }).first()).toBeVisible();
  185 |   await expect(page.getByRole("button", { name: "Open alert 11111111-1111-4111-8111-111111111111" })).toHaveCount(1);
  186 |   await expect(page.getByRole("button", { name: "Open alert email-pod-crash-duplicate.eml" })).toHaveCount(0);
  187 |   await expect(page.locator(".source-email").filter({ hasText: "Email" }).first()).toBeVisible();
  188 |   await expect(page.getByText("Checkout log error burst", { exact: true }).first()).toBeVisible();
  189 |   await expect(page.locator(".source-log").filter({ hasText: "Logs / OpenSearch" }).first()).toBeVisible();
  190 |   await page.getByRole("button", { name: "Open alert 11111111-1111-4111-8111-111111111111" }).click();
  191 |   await expect(page.getByRole("heading", { name: "Alert Details Cockpit" })).toBeVisible();
  192 |   const telemetryProject = page.getByRole("button", { name: /Telemetry telemetry namespace/ });
  193 |   await expect(telemetryProject).toBeVisible();
  194 |   await expect(page.getByText("Telemetry signals missing", { exact: true })).toHaveCount(0);
  195 |   await telemetryProject.click();
  196 |   await expect(page.getByText("Telemetry signals missing", { exact: true }).first()).toBeVisible();
  197 |   await expect(page.getByText("Pod crash loop", { exact: true })).toHaveCount(0);
  198 |   await page.getByRole("button", { name: /KaiOps kaiops namespace/ }).click();
  199 |   expect(alertsAllRequestCount).toBe(1);
  200 | 
  201 |   const firstAlert = page.locator("table tbody tr").filter({ hasText: "Pod crash loop" }).first();
  202 |   await expect(firstAlert).toBeVisible({ timeout: 30_000 });
  203 |   await firstAlert.locator("button").first().click();
  204 | 
  205 |   await expect(page.locator(".alert-details-cockpit .detail-context")).toContainText("11111111-1111-4111-8111-111111111111");
  206 |   await expect(page.locator(".alert-details-cockpit .detail-context")).not.toContainText("email-pod-crash-duplicate.eml");
  207 |   const sectionNavigation = page.getByRole("tablist", { name: "Incident workspace sections" });
  208 |   for (const section of ["Overview", "Evidence", "RCA & Impact", "Resolution", "Approval", "Execution", "Audit Trail"]) {
  209 |     await expect(sectionNavigation.getByRole("tab", { name: section, exact: true })).toBeVisible();
  210 |   }
  211 |   await expect(sectionNavigation.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  212 |   await expect(page.getByRole("heading", { name: "Incident Workspace", exact: true })).toBeVisible();
  213 |   await expect(page.getByRole("heading", { name: "Incident Overview", exact: true })).toBeVisible();
  214 |   await expect(page.locator(".unified-incident-timeline")).toHaveCount(0);
  215 |   await expect(page.getByRole("button", { name: "Previous" })).toBeVisible();
  216 |   await expect(page.getByRole("button", { name: "Next" })).toBeVisible();
  217 |   await page.screenshot({ path: "artifacts/phase5-progressive-incident-cockpit.png", fullPage: true });
  218 | 
  219 |   await sectionNavigation.getByRole("tab", { name: "Audit Trail" }).click();
  220 |   await expect(page.getByRole("heading", { name: "Signal to Recovery", exact: true })).toBeVisible();
  221 |   await expect(page.locator(".unified-incident-timeline")).toBeVisible();
  222 |   await expect(page.locator(".timeline-phase-card")).toHaveCount(6);
  223 |   await expect(page.getByText("Evidence", { exact: true }).first()).toBeVisible();
  224 |   const detectPhase = page.locator(".timeline-phase-card").filter({ hasText: "Detect" });
  225 |   const discoverPhase = page.locator(".timeline-phase-card").filter({ hasText: "Discover" });
  226 |   await detectPhase.getByRole("button", { name: "View events" }).click();
  227 |   await expect(page.locator(".timeline-event-panel")).toHaveCount(1);
  228 |   await expect(page.getByText("Detect events", { exact: true })).toBeVisible();
  229 |   await discoverPhase.getByRole("button", { name: "View events" }).click();
  230 |   await expect(page.locator(".timeline-event-panel")).toHaveCount(1);
  231 |   await expect(page.getByText("Discover events", { exact: true })).toBeVisible();
  232 |   await page.locator(".timeline-event-panel").getByRole("button", { name: "Close" }).click();
  233 |   await expect(page.locator(".timeline-event-panel")).toHaveCount(0);
  234 |   await page.getByRole("button", { name: "Next" }).click();
  235 |   await expect(page.locator(".alert-details-cockpit .detail-context")).toContainText("alert-log-1");
  236 |   await expect(sectionNavigation.getByRole("tab", { name: "Audit Trail" })).toHaveAttribute("aria-selected", "true");
  237 |   await page.getByRole("button", { name: "Previous" }).click();
  238 |   await expect(page.locator(".alert-details-cockpit .detail-context")).toContainText("11111111-1111-4111-8111-111111111111");
  239 | 
  240 |   const discoveryTab = sectionNavigation.getByRole("tab", { name: "RCA & Impact", exact: true });
  241 |   await expect(discoveryTab).toBeVisible();
  242 |   await discoveryTab.click();
  243 |   await expect(page.getByRole("heading", { name: "Discovery + Context", exact: true })).toBeVisible();
  244 |   expect(pageErrors).toEqual([]);
  245 |   await page.getByRole("button", { name: /^Evidence \(/ }).click();
  246 |   await expect(page.locator(".investigation-story")).toContainText("Alert becomes a search plan");
  247 |   await expect(page.locator(".investigation-story")).toContainText("Tools return source facts");
  248 |   await expect(page.locator(".investigation-story")).toContainText("Facts are connected to operations");
  249 |   await expect(page.locator(".investigation-story")).toContainText("RCA and impact are derived");
  250 |   await expect(page.locator(".investigation-story")).toContainText("Evidence becomes an action");
  251 |   const [completeDownload] = await Promise.all([
  252 |     page.waitForEvent("download"),
```