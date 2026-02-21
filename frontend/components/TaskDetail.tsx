import { TaskDetail as TaskDetailType } from '@/lib/api'
import { StatusBadge } from './StatusBadge'
import { TypeBadge } from './TypeBadge'
import { SubmissionTable } from './SubmissionTable'
import { formatDeadline } from '@/lib/utils'

interface Props {
  task: TaskDetailType
}

export function TaskDetail({ task }: Props) {
  const { label, expired } = formatDeadline(task.deadline)

  return (
    <div className="flex flex-col gap-4 p-6 overflow-auto h-full">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-xl font-semibold">{task.title}</h2>
        <div className="flex gap-2 shrink-0">
          <TypeBadge type={task.type} />
          <StatusBadge status={task.status} />
        </div>
      </div>

      <p className="text-muted-foreground text-sm leading-relaxed">{task.description}</p>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {task.threshold !== null && (
          <div>
            <span className="text-muted-foreground">Threshold: </span>
            {task.threshold}
          </div>
        )}
        {task.max_revisions !== null && (
          <div>
            <span className="text-muted-foreground">Max Revisions: </span>
            {task.max_revisions}
          </div>
        )}
        <div>
          <span className="text-muted-foreground">Deadline: </span>
          <span className={expired ? 'text-red-400' : ''}>{label}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Winner: </span>
          {task.winner_submission_id
            ? `🏆 ${task.winner_submission_id.slice(0, 8)}…`
            : '—'}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-medium mb-3">
          Submissions ({task.submissions.length})
        </h3>
        <SubmissionTable submissions={task.submissions} task={task} />
      </div>
    </div>
  )
}
