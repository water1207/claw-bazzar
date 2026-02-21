'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { createTask, createSubmission } from '@/lib/api'

export function DevPanel() {
  // Publish form state
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [type, setType] = useState<'fastest_first' | 'quality_first'>('fastest_first')
  const [threshold, setThreshold] = useState('')
  const [maxRevisions, setMaxRevisions] = useState('')
  const [deadline, setDeadline] = useState('')
  const [publishMsg, setPublishMsg] = useState<string | null>(null)

  // Submit form state
  const [taskId, setTaskId] = useState('')
  const [workerId, setWorkerId] = useState('')
  const [content, setContent] = useState('')
  const [submitMsg, setSubmitMsg] = useState<string | null>(null)

  async function handlePublish(e: React.FormEvent) {
    e.preventDefault()
    setPublishMsg(null)
    try {
      const task = await createTask({
        title,
        description,
        type,
        threshold: threshold ? parseFloat(threshold) : null,
        max_revisions: maxRevisions ? parseInt(maxRevisions, 10) : null,
        deadline: new Date(deadline).toISOString(),
      })
      setPublishMsg(`✅ Published: ${task.id}`)
      setTaskId(task.id)
      setTitle('')
      setDescription('')
      setThreshold('')
      setMaxRevisions('')
      setDeadline('')
    } catch (err) {
      setPublishMsg(`❌ ${(err as Error).message}`)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitMsg(null)
    try {
      const sub = await createSubmission(taskId, { worker_id: workerId, content })
      setSubmitMsg(`✅ Submitted: revision ${sub.revision}, status: ${sub.status}`)
      setContent('')
    } catch (err) {
      setSubmitMsg(`❌ ${(err as Error).message}`)
    }
  }

  return (
    <div className="grid grid-cols-2 gap-10 p-8 max-w-4xl">
      {/* Publish Task */}
      <div>
        <h2 className="text-base font-semibold mb-5">Publish Task</h2>
        <form onSubmit={handlePublish} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Title</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="Task title"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
              rows={3}
              placeholder="Describe the task requirements"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Type</Label>
            <Select
              value={type}
              onValueChange={(v) => setType(v as typeof type)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fastest_first">fastest_first</SelectItem>
                <SelectItem value="quality_first">quality_first</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Threshold{' '}
              <span className="text-muted-foreground text-xs">(fastest_first only)</span>
            </Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              max="1"
              placeholder="0.8"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Max Revisions{' '}
              <span className="text-muted-foreground text-xs">(quality_first only)</span>
            </Label>
            <Input
              type="number"
              min="1"
              placeholder="3"
              value={maxRevisions}
              onChange={(e) => setMaxRevisions(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Deadline</Label>
            <Input
              type="datetime-local"
              required
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
            />
          </div>

          <Button type="submit">Publish</Button>

          {publishMsg && (
            <p className="text-sm font-mono break-all">{publishMsg}</p>
          )}
        </form>
      </div>

      {/* Submit Result */}
      <div>
        <h2 className="text-base font-semibold mb-5">Submit Result</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Task ID</Label>
            <Input
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              required
              placeholder="Auto-filled after publish"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Worker ID</Label>
            <Input
              value={workerId}
              onChange={(e) => setWorkerId(e.target.value)}
              required
              placeholder="my-agent"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Content</Label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              rows={8}
              placeholder="Your submission content..."
            />
          </div>

          <Button type="submit">Submit Result</Button>

          {submitMsg && (
            <p className="text-sm font-mono break-all">{submitMsg}</p>
          )}
        </form>
      </div>
    </div>
  )
}
