"""Progress Persistence Module

Save/load automation job state to survive browser crashes.
Jobs are stored as JSON files in ./data/automation_progress/
"""

import json
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


# Storage directory
PROGRESS_DIR = Path(__file__).parent.parent / "data" / "automation_progress"


@dataclass
class AutomationJob:
    """Represents an automation job that can be saved/resumed."""
    job_id: str
    mode: str  # 'aroll', 'broll_pipeline', 'full'
    items: List[Dict]
    results: Dict[str, Dict] = field(default_factory=dict)
    completed_count: int = 0
    failed_count: int = 0
    status: str = 'pending'  # 'pending', 'running', 'paused', 'completed'
    last_updated: str = ''
    settings: Dict = field(default_factory=dict)
    current_step: str = ''  # 'images', 'videos', 'aroll'
    
    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()
    
    @property
    def total_count(self) -> int:
        return len(self.items)
    
    @property
    def remaining_count(self) -> int:
        return self.total_count - self.completed_count - self.failed_count
    
    @property
    def is_resumable(self) -> bool:
        return self.status in ('running', 'paused') and self.remaining_count > 0
    
    def get_pending_items(self) -> List[Dict]:
        """Get items that haven't been processed yet."""
        processed_ids = set(self.results.keys())
        return [item for item in self.items if item['id'] not in processed_ids]
    
    def update_result(self, item_id: str, result: Dict):
        """Update result for an item and increment counters."""
        self.results[item_id] = result
        if result.get('status') == 'completed':
            self.completed_count += 1
        elif result.get('status') == 'failed':
            self.failed_count += 1
        self.last_updated = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'AutomationJob':
        return cls(**data)


def create_job(
    mode: str,
    items: List[Dict],
    settings: Dict = None
) -> AutomationJob:
    """Create a new automation job."""
    job_id = str(uuid.uuid4())[:8]
    return AutomationJob(
        job_id=job_id,
        mode=mode,
        items=items,
        settings=settings or {}
    )


def save_job(job: AutomationJob) -> None:
    """Save job state to disk."""
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PROGRESS_DIR / f"{job.job_id}.json"
    
    with open(filepath, 'w') as f:
        json.dump(job.to_dict(), f, indent=2)


def load_job(job_id: str) -> Optional[AutomationJob]:
    """Load job state from disk."""
    filepath = PROGRESS_DIR / f"{job_id}.json"
    
    if not filepath.exists():
        return None
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    return AutomationJob.from_dict(data)


def list_resumable_jobs() -> List[Dict]:
    """List all jobs that can be resumed."""
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    
    resumable = []
    for filepath in PROGRESS_DIR.glob("*.json"):
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            job = AutomationJob.from_dict(data)
            if job.is_resumable:
                resumable.append({
                    'job_id': job.job_id,
                    'mode': job.mode,
                    'completed': job.completed_count,
                    'failed': job.failed_count,
                    'total': job.total_count,
                    'last_updated': job.last_updated,
                    'current_step': job.current_step
                })
        except (json.JSONDecodeError, KeyError, TypeError):
            # Skip corrupted files
            continue
    
    # Sort by last_updated descending
    resumable.sort(key=lambda x: x['last_updated'], reverse=True)
    return resumable


def delete_job(job_id: str) -> bool:
    """Delete a job file."""
    filepath = PROGRESS_DIR / f"{job_id}.json"
    
    if filepath.exists():
        filepath.unlink()
        return True
    return False


def cleanup_old_jobs(max_age_days: int = 7) -> int:
    """Delete jobs older than max_age_days."""
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    
    deleted = 0
    cutoff = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)
    
    for filepath in PROGRESS_DIR.glob("*.json"):
        try:
            if filepath.stat().st_mtime < cutoff:
                filepath.unlink()
                deleted += 1
        except OSError:
            continue
    
    return deleted
