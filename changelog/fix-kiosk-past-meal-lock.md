fix: prevent past meal changes in kiosk

- block booking and retraction for meal dates in the past
- keep existing cutoff behavior for next-day caterer ordering
- cover past booking and retraction attempts with kiosk regression tests
