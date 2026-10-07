from app.db.session import SessionLocal
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.services.follow_up_due import FollowUpDueProcessingResult, FollowUpDueService


def run_due_followups() -> FollowUpDueProcessingResult:
    with SessionLocal.begin() as session:
        service = FollowUpDueService(
            session=session,
            follow_up_repository=FollowUpRepository(session),
            audit_repository=LineageRepository(session),
        )
        return service.process_due()


def main() -> None:
    result = run_due_followups()
    print(f"Due follow-ups processed: {result.promoted_count}")


if __name__ == "__main__":
    main()
