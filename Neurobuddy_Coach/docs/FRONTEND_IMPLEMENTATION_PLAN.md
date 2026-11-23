# Neurobuddy Coach Atlas: Cursor integration plan

## Product outcome

The central **Dataset Library is the Repository**. Exactly three application navigation views remain: Dataset Library, Analysis, Advanced Athlete Analysis. The optimized **v0.7.1** pipeline handles EEG analysis without any reimplementation of scientific calculations in the browser. Data must be persisted to disk and SQLite, not simulated in memory.

## Milestones

1. **Foundation / scientific adapter. Implemented in v0.3.** Original three-view UI. FastAPI v0.7.1 integration. A single real EEG can be processed and returned as a structured report. Verify engine version via `/api/v2/health`.
2. **Folder hierarchy and dynamic task-aware shelves. Implemented in v0.3.** Team → Athlete → individual recording shelf. Automatic initial 3 Baseline + 1 Testing placeholders. Dropdowns at top choose Oddball, Sleep, Motor-imagery or Unspecified and Baseline/Testing. Each shelf persists its own task type/classification. `.set` → optional `.fdt` slot; `.vhdr` → `.eeg`/`.vmrk` slots; task-specific events/annotations object shown when relevant. Save/delete files without destroying unrelated shelves. Tests prove persistence after refresh.
3. **Downloads and dataset browser. Local uploads implemented; remote metadata browser implemented, not externally verified.** Local native file picker, preferred Downloads start location if browser supports it; validation and storage of real EEG bytes. Connector opens a context dialog for OpenNeuro ID and browses published snapshot metadata and nested directories; no remote EEG file transfer yet. Additional connectors belong behind a future provider interface, not new navigation tabs.
4. **Drag targets and longitudinal testing. Implemented in v0.3.** Drag one ready shelf to Single EEG; drag athlete to Test Athlete and compare >=3 compatible Baseline EEG recordings to selected task's latest test; drag team to Test Team and generate separate reports for eligible members. Job polling persists status. Real scientific reports in Analysis. UI does not claim task validity when routing finds another task.
5. **Advanced packages. Implemented in v0.3 as local preparation only.** Group completed packages by team and athlete, including results from a team job. Drag/select an object, preview its JSON, download a package. Future AI action remains disabled.
6. **Hardening / acceptance. Ongoing.** More BIDS and real EEG fixtures; verified live OpenNeuro connectivity; follow-up EEG binary transfer; file completion validation; security review; running workload and storage quotas; upload resumability; per-user authentication and encryption; reproducibility and comparison-eligibility gates. Never deploy patient data to current local prototype.

## Non-negotiable acceptance criteria

- Test Type actually changes event/annotation slots and persisted `task_type`; File Type actually changes the Baseline/Testing shelf classification.
- Three Baseline and one Testing shelf are created **empty** for every new athlete. Counting placeholders as completed baseline evidence is forbidden.
- A `.set` upload offers `.fdt` and conditionally a task-event slot. A `.set` with data embedded does not require fabricated `.fdt`.
- Filename alone never determines Oddball/Motor/Sleep routing. The Python scientific router remains authoritative.
- UI plus/delete and drag controls call real endpoints. After reloading the browser, records and files are still present.
- A single EEG report, a three-baseline-plus-test longitudinal comparison, and team batch results are retrievable in Analysis. Advanced results are selectable and exportable without an AI backend.
- An external dataset listing is never confused with a downloaded EEG binary. Read-only remote metadata must not make a shelf processable.
- The older v0.6.1 code is not used. Scientific outputs carry optimized v0.7.1 version metadata.

## Integration interfaces

React is **not** needed to finish the first user journey. Retain the pre-Repository vanilla HTML/JS/CSS design for v0.3. If a future migration to React becomes useful, keep these REST contracts and test the old and new frontends against the same FastAPI server.

`report.json` remains the single authoritative source for scientific measurements. Never recompute Z-scores or P300/motor/sleep statistics in the browser. Browser visualizations should be representations of actual scientific report data, with review warnings and provenance.
