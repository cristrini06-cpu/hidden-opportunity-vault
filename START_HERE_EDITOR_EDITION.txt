HIDDEN OPPORTUNITY VAULT — FULL EDITOR & PUBLISHING REBUILD
October 29, 2026 | Same public website and GitHub repository

WHAT IS FIXED
- The source-linked listing form now supports cash prizes, grants, collaboration,
  paid research, trial products, vouchers, refunds, travel, beta access and more.
- Reward category, advertised amount, qualifying audience, exact eligibility,
  application steps, important terms, review status and deadline are editable.
- Scanner lead forms prefill known award and deadline, but NEVER auto-approve.
- A pending/draft listing can be saved in the owner's browser without publication.
- Public-export eligibility requires: verified review decision, independent
  official-source checkbox, provider, exact reward, detailed eligibility,
  important restrictions, application instructions, and a verified date.
- Both verified newly created listings and verified edits can be exported.
- Export filename is 'approved.json', matching the GitHub publishing path.
- The GitHub publishing validator now rejects missing terms, eligibility,
  application instructions, unverified records and already-expired open calls.
- Detailed opportunity pages display the editor's actual award and eligibility.
- Existing 40 departments, 120 entries, scanner, clock, alerts, controls and
  site layout remain in place. Scanner history is not bundled or reset.

UPDATE THE EXISTING LIVE WEBSITE
1. Download this ZIP; choose Extract All on Windows.
2. Open the extracted folder until you see index.html, agent, tools and .github.
3. Sign in to the existing GitHub repository as its owner:
   https://github.com/cristrini06-cpu/hidden-opportunity-vault
4. Choose Code > Add file > Upload files, and upload the CONTENTS of that
   extracted folder, not the ZIP or enclosing folder.
5. Confirm the upload shows: index.html, tools/validate_approved.py,
   agent/monitor.py, .github/workflows/publish-website.yml.
6. Commit directly to main. Check the Publish Verified Website workflow.
7. Open https://cristrini06-cpu.github.io/hidden-opportunity-vault/
   and press Ctrl+F5. Check the form and navigation.

DO NOT DELETE OR REPLACE THE EXISTING agent/data/ DIRECTORY.
This ZIP deliberately contains no generated scanner reports or stored approvals.

PUBLISH ONE EDITOR-VERIFIED OPPORTUNITY FOR ALL VISITORS
A. Click Daily Agent, then Verify Details for a genuinely current lead.
B. Open the ORIGINAL SOURCE yourself; check organizer, eligibility, expiry,
   exact benefit, restrictions, costs/returns, and how to apply.
C. In the listing editor, set the correct Reward type, Specific benefit,
   Advertised reward, country and eligibility. Write precise terms and steps.
D. Select Editorial review decision = Verified by editor; choose Open program
   (or Invitation only) ONLY if truly current and eligible. Check the official
   verification checkbox and supply the actual review date.
E. Save locally. Click Export > Approved local listings JSON (or the button
   shown in Daily Agent). Download approved.json.
F. On GitHub, open agent/data/ and upload approved.json THERE, replacing the
   existing approved.json (not into the repository root).
G. Commit to main. Publish Verified Website validates and deploys the file.
H. Check the public site in a private window: the new record should appear.

SECURITY / LIMITATIONS
- GitHub Pages is STATIC: editing is local, not authenticated administration.
  Any public visitor may open local editing controls; only a GitHub contributor
  can change the repository and publish to everyone. Do not enter secrets.
- Source verification is a human editorial judgment, not an automated truth
  certification. No reward is guaranteed.
- Offline tests do not guarantee all third-party websites remain accessible.
- This package has not itself been uploaded to the user's GitHub account.

QA: JavaScript syntax clean; 31 scanner tests; desktop browser end-to-end
form tests; public JSON validator pass/reject; 40 departments; mobile checks.
