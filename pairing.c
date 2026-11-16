#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <inttypes.h>

typedef struct {
    bool has_reference;
    uint64_t last_pulse;
} Pairing;

static const char *observe(Pairing *state, uint64_t pulse, uint64_t phase_ns,
                           uint64_t age_ns, uint64_t window_ns,
                           bool check_age, uint64_t max_age_ns) {
    if (phase_ns > window_ns) {
        return "outside_window";
    }
    if (check_age && age_ns > max_age_ns) {
        return "expired";
    }
    if (state->has_reference && pulse <= state->last_pulse) {
        return "already_matched";
    }
    state->has_reference = true;
    state->last_pulse = pulse;
    return "accepted";
}

int main(void) {
    uint64_t window_ns, max_age_ns;
    if (scanf("%" SCNu64 " %" SCNu64, &window_ns, &max_age_ns) != 2) {
        fputs("Expected window and maximum age in nanoseconds\n", stderr);
        return 1;
    }

    Pairing phase_only = {0};
    Pairing source_age = {0};
    uint64_t pulse, phase_ns, age_ns;
    int fields;
    while ((fields = scanf("%" SCNu64 " %" SCNu64 " %" SCNu64,
                           &pulse, &phase_ns, &age_ns)) == 3) {
        const char *baseline = observe(&phase_only, pulse, phase_ns, age_ns,
                                       window_ns, false, max_age_ns);
        const char *guard = observe(&source_age, pulse, phase_ns, age_ns,
                                    window_ns, true, max_age_ns);
        printf("%s %s\n", baseline, guard);
    }
    if (fields != EOF || ferror(stdin)) {
        fputs("Expected pulse, phase and nonnegative message age\n", stderr);
        return 1;
    }
    return 0;
}
