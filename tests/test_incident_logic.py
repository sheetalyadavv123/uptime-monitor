# =============================================================================
# tests/test_incident_logic.py  -  WHEN IS A SITE "DOWN"?
# =============================================================================
# These tests check the pure function `decide_next_state`. No database and no
# network are needed, so they run instantly. Read the state diagram in
# docs/08-incidents-and-alerts.md next to these tests.
# =============================================================================
from app.services.incidents import StatusEvent, decide_next_state


# Test: passing check makes monitor up without event.
def test_passing_check_makes_monitor_up_without_event():
    state = decide_next_state("unknown", 0, check_passed=True, failure_threshold=3)
    assert (state.status, state.consecutive_failures, state.event) == ("up", 0, None)


# Test: one failure is not enough to go down.
def test_one_failure_is_not_enough_to_go_down():
    state = decide_next_state("up", 0, check_passed=False, failure_threshold=3)
    assert (state.status, state.consecutive_failures, state.event) == ("up", 1, None)


# Test: reaching the threshold goes down and reports it.
def test_reaching_the_threshold_goes_down_and_reports_it():
    state = decide_next_state("up", 2, check_passed=False, failure_threshold=3)
    assert (state.status, state.consecutive_failures, state.event) == (
        "down",
        3,
        StatusEvent.WENT_DOWN,
    )


# Test: failing while already down reports nothing new.
def test_failing_while_already_down_reports_nothing_new():
    state = decide_next_state("down", 3, check_passed=False, failure_threshold=3)
    assert (state.status, state.consecutive_failures, state.event) == ("down", 4, None)


# Test: passing while down recovers and resets counter.
def test_passing_while_down_recovers_and_resets_counter():
    state = decide_next_state("down", 5, check_passed=True, failure_threshold=3)
    assert (state.status, state.consecutive_failures, state.event) == (
        "up",
        0,
        StatusEvent.RECOVERED,
    )


# Test: unknown monitor that keeps failing stays unknown until threshold.
def test_unknown_monitor_that_keeps_failing_stays_unknown_until_threshold():
    state = decide_next_state("unknown", 0, check_passed=False, failure_threshold=2)
    assert state.status == "unknown" and state.event is None


# Test: threshold of one goes down immediately.
def test_threshold_of_one_goes_down_immediately():
    state = decide_next_state("up", 0, check_passed=False, failure_threshold=1)
    assert state.status == "down" and state.event == StatusEvent.WENT_DOWN


# Test: a full story from up to down to up.
def test_a_full_story_from_up_to_down_to_up():
    # Follows one monitor through 6 checks. Threshold is 3.
    status, failures = "unknown", 0
    events = []
    for passed in [True, False, False, False, False, True]:
        state = decide_next_state(status, failures, passed, failure_threshold=3)
        status, failures = state.status, state.consecutive_failures
        events.append(state.event)

    assert events == [None, None, None, StatusEvent.WENT_DOWN, None, StatusEvent.RECOVERED]
    assert status == "up"
