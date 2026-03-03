import sys

from healthcheck_utils import HEARTBEAT_MAX_AGE_SECONDS, heartbeat_age_seconds


def check_health() -> tuple[bool, list[str]]:
    problems = []
    for name in ("main", "da_polling"):
        age = heartbeat_age_seconds(name)
        if age is None:
            problems.append(f"{name}: missing heartbeat")
            continue
        if age > HEARTBEAT_MAX_AGE_SECONDS:
            problems.append(
                f"{name}: stale heartbeat ({int(age)}s > {HEARTBEAT_MAX_AGE_SECONDS}s)"
            )
    return not problems, problems


def main() -> int:
    healthy, problems = check_health()
    if healthy:
        return 0

    for problem in problems:
        print(problem, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
