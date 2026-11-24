# Dataset Library reception contract (v0.2 preview only)

The future **Neuro-bud Repository** is not present in this release. This contract establishes where and how a hierarchy object can be dropped into the **Dataset Library's Teams & Athletes panel** without creating or importing actual EEG files today.

## DataTransfer integration

From a future Repository draggable hierarchy object:

```js
const MIME = 'application/x-neurobuddy-library+json';
objectElement.addEventListener('dragstart', event => {
  event.dataTransfer.effectAllowed = 'copy';
  event.dataTransfer.setData(MIME, JSON.stringify(hierarchy));
});
```

The receiving page already listens for that MIME type. It also exposes:

```js
window.NeurobuddyLibraryReceiver.receive(hierarchy);
window.dispatchEvent(new CustomEvent('neurobuddy:library-transfer', {detail: hierarchy}));
```

## Object shape

```json
{
  "schema_version": "neurobuddy.library-transfer/1",
  "teams": [
    {
      "name": "Track Team",
      "athletes": [
        {
          "name": "Athlete A",
          "baseline": [
            {
              "name": "rest-baseline-01.set",
              "files": [
                { "name": "rest-baseline-01.set", "size_bytes": 1048576 },
                { "name": "rest-baseline-01.fdt", "size_bytes": 12582912 }
              ]
            },
            { "name": "rest-baseline-02.edf", "files": ["rest-baseline-02.edf"] }
          ],
          "testing": [
            { "name": "rest-test-01.edf", "files": ["rest-test-01.edf"] }
          ]
        }
      ]
    }
  ]
}
```

**Behavior now:** Receiving the object displays expandable Team, Athlete, Baseline, and Testing groups. The folders are **preview-only**, do not persist after a browser refresh, and do not enable EEG processing. The existing, backend-managed library is not overwritten or deleted. A **Clear preview** button returns to the backend-backed library.

**Future work:** The Repository needs to resolve its own file handles to actual stored EEG recordings and upload or reference the real signal/companion bytes using the authorized backend, then publish/persist the hierarchy. Only verified, backend-stored recording IDs should become selectable in the processing panel. Files must not be reconstructed from displayed filenames. This phase has intentionally *not* been implemented.

The receiver rejects payloads with an unsupported schema, no teams, malformed folder arrays, or oversized hierarchies. Input strings are HTML-escaped before rendering; a drop does not execute code.
