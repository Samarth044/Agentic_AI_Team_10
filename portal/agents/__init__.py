"""Portal agents. The six Worklet 10 agents (PPT slide 15) plus the Resume
Agent that feeds them, the career assistant and three supporting agents."""


def set_stage(record_id: str, stage: str, **fields) -> None:
    from .. import db
    db.update("records", record_id, {"stage": stage, "updated_at": db.now(), **fields})


from .resume import ResumeAgent  # noqa: E402
from .discovery import OpportunityDiscoveryAgent  # noqa: E402
from .eligibility import EligibilityVerificationAgent  # noqa: E402
from .application import ApplicationProcessingAgent  # noqa: E402
from .approval import ApprovalAgent  # noqa: E402
from .progress import ProgressTrackingAgent  # noqa: E402
from .evaluation import EvaluationAgent  # noqa: E402
from .assistant import CareerAssistant  # noqa: E402
from .panel import ExpertPanel  # noqa: E402
from .research import CompanyResearchAgent  # noqa: E402
from .ops import OpsAgent  # noqa: E402
from .policy import PolicyAgent  # noqa: E402

WORKLET_AGENTS = [OpportunityDiscoveryAgent, EligibilityVerificationAgent,
                  ApplicationProcessingAgent, ApprovalAgent, ProgressTrackingAgent, EvaluationAgent]
ALL_AGENTS = [ResumeAgent, *WORKLET_AGENTS, CareerAssistant, ExpertPanel, CompanyResearchAgent,
              PolicyAgent, OpsAgent]
