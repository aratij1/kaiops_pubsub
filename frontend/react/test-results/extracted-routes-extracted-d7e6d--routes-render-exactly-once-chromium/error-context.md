# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: extracted-routes.spec.js >> extracted Copilot and Closed Incidents routes render exactly once
- Location: tests/e2e/extracted-routes.spec.js:3:1

# Error details

```
Error: expect(locator).toHaveCount(expected) failed

Locator:  getByRole('heading', { name: 'Human Approval Queue', exact: true })
Expected: 1
Received: 0
Timeout:  5000ms

Call log:
  - Expect "toHaveCount" with timeout 5000ms
  - waiting for getByRole('heading', { name: 'Human Approval Queue', exact: true })
    12 × locator resolved to 0 elements
       - unexpected value "0"

```

```
Error: apiRequestContext._wrapApiCall: ENOMEM: not enough memory, read
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
            - option "Real Use Cases" [selected]
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
              - button "Approvals" [active] [ref=e50] [cursor=pointer]:
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
        - heading "Approvals" [level=1] [ref=e135]
        - paragraph [ref=e136]: review · decision · human gate
        - navigation "Breadcrumb" [ref=e137]:
          - list [ref=e138]:
            - listitem [ref=e139]: Operations
            - listitem [ref=e140]: /Approvals
        - generic [ref=e141]:
          - generic [ref=e142]: api-gateway is ok
          - generic [ref=e144]: "Monitoring: Real Use Cases"
          - generic [ref=e145]: "Signed in: admin (Administrator)"
          - button "Logout" [ref=e146] [cursor=pointer]
        - navigation "Related workflow destinations" [ref=e147]:
          - generic [ref=e148]: "Continue workflow:"
          - button "Incidents" [ref=e149] [cursor=pointer]
          - button "Closed Incidents" [ref=e150] [cursor=pointer]
      - group "Global operational capabilities" [ref=e151]:
        - generic "Search & personal work Find records, assignments, and notifications ⌄" [ref=e152] [cursor=pointer]:
          - generic [ref=e153]: Search & personal work
          - generic [ref=e154]: Find records, assignments, and notifications
          - text: ⌄
        - generic [ref=e155]:
          - tablist "Global operations" [ref=e156]:
            - tab "Search" [selected] [ref=e157] [cursor=pointer]
            - tab "My Work (0)" [ref=e158] [cursor=pointer]
            - tab "Notifications (0)" [ref=e159] [cursor=pointer]
          - generic [ref=e160]:
            - generic [ref=e161]:
              - generic [ref=e162]: Global search
              - searchbox "Global search" [ref=e163]
            - paragraph [ref=e164]: Searches currently loaded, role-authorized operational records.
      - generic [ref=e165]:
        - article [ref=e166]:
          - generic [ref=e167]:
            - text: HUMAN DECISION OPERATIONS
            - heading "Approval Workspace" [level=2] [ref=e168]
            - paragraph [ref=e169]: Balance responder capacity, route pending tickets, and make one evidence-backed decision at a time.
          - generic [ref=e170]:
            - generic [ref=e171]:
              - strong [ref=e172]: "0"
              - generic [ref=e173]: Pending
            - generic [ref=e174]:
              - strong [ref=e175]: "0"
              - generic [ref=e176]: Available profiles
            - generic [ref=e177]:
              - strong [ref=e178]: "0"
              - generic [ref=e179]: Assigned
        - navigation "Approval workspace sections" [ref=e180]:
          - button "Queue" [ref=e181] [cursor=pointer]
          - button "Capacity & assignment" [ref=e182] [cursor=pointer]
          - button "Review & decide" [ref=e183] [cursor=pointer]
          - button "Assignment history" [ref=e184] [cursor=pointer]
        - article [ref=e185]:
          - generic [ref=e186]:
            - generic [ref=e187]:
              - heading "Pending approval queue" [level=3] [ref=e188]
              - paragraph [ref=e189]: Select a ticket to review, or assign the queue using responder capacity.
            - button "Auto-assign pending tickets" [ref=e190] [cursor=pointer]
          - generic [ref=e192]:
            - text: Filter
            - combobox "Filter" [ref=e193]:
              - option "all" [selected]
              - option "awaiting_approval"
              - option "critical"
              - option "high"
              - option "medium"
              - option "low"
          - paragraph [ref=e195]: No pending approvals match this filter.
```