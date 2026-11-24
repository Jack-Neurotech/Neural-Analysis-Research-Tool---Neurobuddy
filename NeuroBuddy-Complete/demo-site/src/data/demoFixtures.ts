export type TaskType = 'oddball' | 'motor' | 'sleep' | 'unspecified'
export type FileClass = 'baseline' | 'testing'
export type SlotKind = 'required' | 'companion' | 'optional'

export const PRODUCT = {
  name: 'Neurobuddy',
  engine: 'v0.7.1 optimized',
  coachUi: 'Coach Atlas v0.3.1',
  tagline: 'From EEG recordings to structured scientific insight.',
  subtext:
    'Organize recordings, run task-aware EEG analysis, compare measurements over time, and explore reproducible reports.',
  disclaimer:
    'Interactive product tour. No live EEG processed.',
  sampleMark: 'Interactive demo · illustrative sample data',
  implementHref: 'https://www.athleticperformanceintelligence.com/',
  implementLabel: 'Implement Neurobuddy',
} as const

export const SIGNAL_EXTENSIONS = ['.set', '.edf', '.bdf', '.vhdr', '.fif', '.fif.gz'] as const
export const COMPANION_NOTES = {
  set: '.fdt only when the .set references external EEGLAB data',
  vhdr: '.eeg and .vmrk for BrainVision',
} as const
export const AUX_EXTENSIONS = ['.tsv', '.json', '.csv', '.txt'] as const

export const BASELINE_RULES = {
  oddball: { minBaselines: 2, test: 1, note: 'Oddball may use two baselines in current implementation.' },
  motor: { minBaselines: 3, test: 1, note: 'Motor imagery requires at least three compatible baselines plus a test.' },
  sleep: { minBaselines: 3, test: 1, note: 'Sleep requires at least three compatible baselines plus a test.' },
  unspecified: { minBaselines: 3, test: 1, note: 'Unspecified requires at least three compatible baselines plus a test.' },
} as const

export const Z_THRESHOLD = 3
export const PIPELINE_STEPS = [
  {
    id: 'athlete',
    title: 'Choose an athlete',
    body: 'Recordings stay nested under a team and athlete so later comparisons can be attributed to one person, not mixed across a roster.',
  },
  {
    id: 'shelves',
    title: 'Organize EEG shelves',
    body: 'Each shelf holds one primary signal plus optional companions and events. New athletes start with three empty baseline shelves and one empty testing shelf.',
  },
  {
    id: 'task',
    title: 'Select test type',
    body: 'Oddball, motor imagery, sleep, or unspecified changes which event slots appear. Scientific routing still inspects the recording; a menu choice does not override evidence.',
  },
  {
    id: 'run',
    title: 'Run analysis',
    body: 'Single EEG, athlete longitudinal, or team batch. Completed jobs open the original pipeline HTML report when the pathway produced one.',
  },
  {
    id: 'reports',
    title: 'Review reports',
    body: 'The product links to original HTML reports, figure tables, a brain activity player, comparisons, sleep replay, and exported artifacts when the pathway produced them.',
  },
] as const

export const TASKS: Record<
  TaskType,
  {
    label: string
    short: string
    explanation: string
    why: string
    caveat: string
    photo: { src: string; alt: string; caption: string }
    slots: { kind: SlotKind; label: string; detail: string }[]
  }
> = {
  oddball: {
    label: 'Oddball',
    short: 'Stimulus-linked ERP',
    explanation:
      'Oddball pathway: stimulus-linked EEG; target/standard event labels; P300/N200 and ERP waveforms when usable event data exists.',
    why: 'Task-aware evented analysis and longitudinal comparison.',
    caveat:
      'The photograph is atmospheric and does not show an Oddball trial. Balancing is not what this pathway measures. Without identifiable target/standard events, specialized ERP metrics are not valid.',
    slots: [
      { kind: 'required', label: 'EEG signal', detail: '.set / .edf / .bdf / .vhdr / .fif / .fif.gz' },
      { kind: 'companion', label: 'Referenced companion', detail: '.fdt if .set points outside; .eeg/.vmrk for BrainVision' },
      { kind: 'optional', label: 'Events / task object', detail: 'events.tsv or embedded markers — not a raw EEG substitute' },
    ],
    photo: {
      src: '/media/task-oddball.jpg',
      alt: 'Adult balancing on one foot while wearing a research EEG electrode cap',
      caption: 'Atmospheric photograph. Oddball is a stimulus-linked ERP pathway, not a balance test.',
    },
  },
  motor: {
    label: 'Motor imagery',
    short: 'Mu / beta ERD/ERS',
    explanation:
      'Motor imagery in the product is documented motor cues and mu/beta ERD/ERS near C3/C4. It does not measure exertion or recovery from EEG alone.',
    why: 'Run the motor-imagery path when documented motor cues exist; do not read this card as a fitness or recovery score.',
    caveat: 'The photograph is atmospheric. Physical load, heart rate, and readiness scores are not computed from these recordings.',
    slots: [
      { kind: 'required', label: 'EEG signal', detail: '.set / .edf / .bdf / .vhdr / .fif / .fif.gz' },
      { kind: 'companion', label: 'Referenced companion', detail: '.fdt if required by .set; .eeg/.vmrk for .vhdr' },
      { kind: 'optional', label: 'Motor cue events', detail: 'Cue annotations when markers are not embedded' },
    ],
    photo: {
      src: '/media/task-motor.jpg',
      alt: 'Adult performing a controlled lunge while wearing an EEG earpiece',
      caption: 'Atmospheric photograph. This pathway is Motor imagery, not an exertion or recovery measurement.',
    },
  },
  sleep: {
    label: 'Sleep',
    short: 'Stages and spectral features',
    explanation:
      'Sleep pathway: scored or optionally estimated stages; hypnogram, stage durations, spectral features, candidate spindles/slow waves where prerequisites permit. Automatically staged results are unreviewed.',
    why: 'Organize sleep recordings, run the sleep analysis path, and review reports.',
    caveat: 'Estimated stages are research screening, not a scored clinical hypnogram.',
    slots: [
      { kind: 'required', label: 'EEG signal', detail: '.set / .edf / .bdf / .vhdr / .fif / .fif.gz' },
      { kind: 'companion', label: 'Referenced companion', detail: 'Only when the chosen signal format requires it' },
      { kind: 'optional', label: 'Stage annotations', detail: 'Scored stages preferred; optional estimation if missing' },
    ],
    photo: {
      src: '/media/task-sleep.jpg',
      alt: 'Adult sleeping while wearing a research EEG electrode cap',
      caption: 'Demonstration photograph of sleep recording setup. Illustrative only; no live EEG is processed.',
    },
  },
  unspecified: {
    label: 'Unspecified',
    short: 'General channel statistics',
    explanation:
      'Unspecified / GENERAL: general channel statistics, frequency power, signal quality, and Hjorth measurements. No specialized events are necessary.',
    why: 'Use when the recording has no specialized event protocol, or when you want channel statistics without inventing a task.',
    caveat: 'A GENERAL route is not a diagnosis and does not invent P300 or sleep architecture.',
    slots: [
      { kind: 'required', label: 'EEG signal', detail: '.set / .edf / .bdf / .vhdr / .fif / .fif.gz' },
      { kind: 'companion', label: 'Referenced companion', detail: '.fdt / .eeg / .vmrk only if the signal format needs them' },
      { kind: 'optional', label: 'Metadata sidecars', detail: '.tsv / .json annotations — never a raw EEG replacement' },
    ],
    photo: {
      src: '/media/task-unspecified.jpg',
      alt: 'Research EEG electrode cap resting unused on a stand beside a closed laptop',
      caption: 'Idle research cap. Unspecified is general channel statistics, not a specialized task.',
    },
  },
}

export const REPORT_PATHWAYS: Record<
  TaskType,
  {
    label: string
    short: string
    diagrams: string[]
    uniqueStats: string[]
    message: string
  }
> = {
  oddball: {
    label: 'Oddball',
    short: 'Stimulus-linked ERP HTML',
    diagrams: [
      'Oddball ERP: target vs standard vs difference at Pz (or Cz), with a 250–500 ms P300 window marked',
      'Optional reaction-time histogram when timestamped responses can be matched to stimuli',
      'Shared channel figures: waveform, Welch spectrum, relative band power, RMS, heuristic quality',
      'Brain activity player in the HTML when a scalp montage can be mapped',
    ],
    uniqueStats: [
      'Target / standard event counts; ERP only when both conditions exist',
      'P300 and N200 difference mean, peak, and latency at the selected electrode',
      'Exploratory Welch trial mean-amplitude t-test in the 250–500 ms window (not confirmatory inference)',
      'Optional d-prime and onset-based reaction times when response events are timestamped',
    ],
    message:
      'These figures show a stimulus-linked ERP contrast when usable target/standard events exist. They are not a diagnosis. Without identifiable events, specialized ERP metrics are omitted.',
  },
  sleep: {
    label: 'Sleep',
    short: 'Hypnogram HTML',
    diagrams: [
      'Scored hypnogram, or an automated hypnogram labeled unreviewed when stages were estimated',
      'Stage-specific band powers at a representative EEG channel (C3/C4/Cz when present)',
      'Optional spindle and slow-wave counts by hour where N2/N3 prerequisites permit',
      'Interactive sleep replay in the HTML: scored or estimated stages, not reconstructed raw EEG',
    ],
    uniqueStats: [
      'Time by stage, total sleep time, and stage transitions from scored or estimated intervals',
      'Optional YASA estimated stages; automatically staged results are unreviewed',
      'Candidate spindle and slow-wave summaries when detectors can run',
      'Sleep efficiency is not reported unless lights-off/on boundaries are verified',
    ],
    message:
      'These figures describe scored or estimated sleep architecture. Estimated stages are research screening, not a scored clinical hypnogram, and not a medical finding.',
  },
  motor: {
    label: 'Motor imagery',
    short: 'Mu / beta ERD/ERS HTML',
    diagrams: [
      'Motor mu ERD/ERS bars at C3 and C4 by cue (negative values are desynchronization)',
      'Shared channel figures: waveform, spectrum, relative band power, RMS, heuristic quality',
      'Brain activity player in the HTML when montage mapping is available',
    ],
    uniqueStats: [
      'Cue counts for documented motor labels (left/right hand, both hands, both feet)',
      'ERD/ERS percent: 100 × (post-cue − pre-cue band power) / pre-cue, mu 8–12 Hz and beta 13–30 Hz',
      'Pre-cue window −1.5 to −0.25 s; post-cue +0.5 to +2.5 s, near C3/C4',
    ],
    message:
      'These figures show spectral change around documented motor cues. Motor imagery in this product does not measure exertion or recovery from EEG alone.',
  },
  unspecified: {
    label: 'Unspecified',
    short: 'General channel-stats HTML',
    diagrams: [
      'Raw vs window-filtered waveform on a representative channel',
      'Welch power spectrum and relative band power by channel',
      'Channel RMS and heuristic IONM-style quality grades (unvalidated screening)',
    ],
    uniqueStats: [
      'Per-channel statistics, frequency power, and Hjorth activity / mobility / complexity',
      'Heuristic quality grades and SNR-style proxies with engine warnings',
      'No specialized event object; no P300, ERD/ERS, or hypnogram invented',
    ],
    message:
      'These figures summarize general channel statistics. A GENERAL route is not a diagnosis and does not invent Oddball, motor, or sleep architecture.',
  },
}

export type DemoFile = { id: string; name: string; role: 'signal' | 'companion' | 'events' }
export type DemoShelf = {
  id: string
  classification: FileClass
  taskType: TaskType
  files: DemoFile[]
}
export type DemoAthlete = { id: string; name: string; shelves: DemoShelf[] }
export type DemoTeam = { id: string; name: string; athletes: DemoAthlete[] }

export const DEFAULT_LIBRARY: DemoTeam[] = [
  {
    id: 'team-atlas',
    name: 'Atlas Sprint Lab',
    athletes: [
      {
        id: 'ath-rivera',
        name: 'Athlete Rivera',
        shelves: [
          { id: 'shelf-b1', classification: 'baseline', taskType: 'oddball', files: [] },
          { id: 'shelf-b2', classification: 'baseline', taskType: 'oddball', files: [] },
          { id: 'shelf-b3', classification: 'baseline', taskType: 'oddball', files: [] },
          { id: 'shelf-t1', classification: 'testing', taskType: 'oddball', files: [] },
        ],
      },
    ],
  },
]

export const PROCESSING_PLACEHOLDER = {
  name: 'nb031_test_signal.fif',
  note: 'Filename shown as a layout example from the Coach screenshots. This demo never reads a visitor file.',
}

export const ARTIFACT_WINDOWS = [
  { start: 2.4, end: 3.1, channel: 'Fp1', flag: 'rms_burst' },
  { start: 6.8, end: 7.6, channel: 'T7', flag: 'jump' },
] as const

export const FILE_STATUS_STEPS = ['Processing', 'Analysis', 'Report ready'] as const

export const COMPARISON_CARDS = [
  { id: 'b1', label: 'Baseline 1', file: 'rivera_oddball_b1.set', role: 'baseline' as const },
  { id: 'b2', label: 'Baseline 2', file: 'rivera_oddball_b2.set', role: 'baseline' as const },
  { id: 'b3', label: 'Baseline 3', file: 'rivera_oddball_b3.set', role: 'baseline' as const },
  { id: 't1', label: 'Testing', file: 'rivera_oddball_test.set', role: 'testing' as const },
]

export const Z_MATRIX = [
  {
    metric: 'Pz P300 peak amplitude',
    unit: 'µV',
    baselineValues: [8.42, 8.96],
    baselineMean: 8.69,
    baselineSd: 0.381837,
    testValue: 7.21,
    zScore: -3.8765,
    cv: 0.04394,
    flag: 'warning' as const,
  },
  {
    metric: 'Fz N200 peak amplitude',
    unit: 'µV',
    baselineValues: [-4.1, -4.28],
    baselineMean: -4.19,
    baselineSd: 0.127279,
    testValue: -4.35,
    zScore: -1.257,
    cv: 0.03038,
    flag: 'within' as const,
  },
  {
    metric: 'Cz band power 8–12 Hz',
    unit: 'µV²/Hz',
    baselineValues: [12.04, 12.51],
    baselineMean: 12.275,
    baselineSd: 0.33234,
    testValue: 12.18,
    zScore: -0.2859,
    cv: 0.02707,
    flag: 'within' as const,
  },
] as const

export const SAMPLE_JOBS = [
  {
    id: 'job-2abda5c5',
    title: 'Single EEG · Athlete Rivera',
    when: 'Sample timestamp · not a live run',
    status: 'completed' as const,
    kind: 'single' as const,
  },
  {
    id: 'job-long-19',
    title: 'Athlete longitudinal · Rivera',
    when: 'Sample timestamp · not a live run',
    status: 'completed' as const,
    kind: 'athlete' as const,
  },
  {
    id: 'job-team-04',
    title: 'Team batch · Atlas Sprint Lab',
    when: 'Sample timestamp · not a live run',
    status: 'completed' as const,
    kind: 'team' as const,
  },
] as const

export const COACHING_STRUGGLES = [
  {
    id: 'complete-view',
    source: 'api',
    label: 'No Complete View of the Athlete',
    body: "Athlete information is spread across training logs, readiness reports, coaching notes and other tools. Teams may not have one place to see the athlete's physical, mental and behavioral information together.",
  },
  {
    id: 'decision-support',
    source: 'api',
    label: 'Limited Decision Support',
    body: 'Coaches and performance teams often have to make decisions using incomplete or disconnected information. This makes it harder to see what is happening in real time.',
  },
  {
    id: 'manual-work',
    source: 'api',
    label: 'Too Much Manual Work',
    body: "Coaching staffs can spend a lot of time tracking data, switching between platforms and creating reports because their systems aren't connected.",
  },
  {
    id: 'clear-insights',
    source: 'api',
    label: 'Data Without Clear Insights',
    body: "Many tools provide data and dashboards, but don't explain what the information means or what teams should consider next.",
  },
  {
    id: 'gaps',
    source: 'api',
    label: 'Where These Gaps Show Up',
    body: 'These challenges can affect individual athlete performance, recovery, injury prevention and the ability of coaches and performance teams to make informed decisions.',
  },
  {
    id: 'neurobuddy',
    source: 'neurobuddy',
    label: 'How Neurobuddy gathers neural analysis',
    body: 'Neurobuddy organizes EEG under a team folder, an athlete folder, and shelves, then runs task-aware analysis for Oddball, sleep, motor imagery, or unspecified recordings. Completed jobs open the original pipeline HTML report: pathway diagrams and statistics for review, not a diagnosis. That report is one neural measurement thread staff can read next to training, recovery, and readiness information. This tour uses illustrative sample data; it does not record or analyze visitor EEG.',
  },
] as const

export const RESEARCH_CAPTION =
  'This demonstration does not provide medical diagnoses, validated fatigue or recovery scores, or real-time EEG analysis.'
