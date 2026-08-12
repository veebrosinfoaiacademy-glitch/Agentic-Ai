import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import * as contentApi from '../api/content'
import {
  Alert,
  BulletList,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ProseBlock,
  ResultMeta,
  Select,
  TextArea,
  TextInput,
} from '../components/common'
import { friendlyError, humanise } from '../utils/errorMessages'

/**
 * Every option list below mirrors a backend enum exactly. Sending a value the
 * server does not accept would be rejected with a 422, so the selects are
 * generated from the same vocabularies the Pydantic schemas define.
 */
const CONTENT_TYPES = [
  'blog', 'article', 'email', 'social_media', 'technical_explanation',
  'product_description',
]
const TONES = [
  'professional', 'formal', 'friendly', 'casual', 'persuasive', 'simple',
  'academic',
]
const AUDIENCES = [
  'beginner', 'student', 'developer', 'technical_professional',
  'general_audience', 'executive',
]
const LENGTHS = ['short', 'medium', 'long']
const SUMMARY_TYPES = ['short', 'detailed', 'bullet_points']
const FORMATS = ['paragraph', 'bullet_points', 'article', 'email', 'report', 'social_media']

const asOptions = (values) => values.map((value) => ({ value, label: humanise(value) }))

const TASKS = [
  { id: 'generate', label: 'Generate', busy: 'Generating…' },
  { id: 'summarize', label: 'Summarize', busy: 'Summarizing…' },
  { id: 'rewrite', label: 'Rewrite', busy: 'Rewriting…' },
  { id: 'tone', label: 'Change tone', busy: 'Transforming…' },
  { id: 'audience', label: 'Adapt for audience', busy: 'Adapting…' },
  { id: 'format', label: 'Change format', busy: 'Reformatting…' },
  { id: 'extract', label: 'Extract information', busy: 'Extracting…' },
]

const INITIAL_FORM = {
  topic: '',
  content_type: 'blog',
  tone: 'professional',
  audience: 'general_audience',
  length: 'medium',
  additional_instructions: '',
  text: '',
  instructions: '',
  summary_type: 'short',
  target_tone: 'professional',
  target_audience: 'beginner',
  format: 'bullet_points',
}

export default function ContentAgent() {
  const location = useLocation()
  const [task, setTask] = useState('generate')
  const [form, setForm] = useState(INITIAL_FORM)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Text handed over from the Documents page via router state. No backend
  // endpoint was invented for this — it is purely frontend state.
  useEffect(() => {
    const handedOver = location.state?.text
    if (handedOver) {
      setForm((prev) => ({ ...prev, text: handedOver }))
      setTask('summarize')
    }
  }, [location.state])

  function update(field) {
    return (event) => setForm((prev) => ({ ...prev, [field]: event.target.value }))
  }

  function changeTask(nextTask) {
    setTask(nextTask)
    setResult(null)
    setError(null)
    setFieldErrors({})
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (isSubmitting) return // guards against double-clicks

    setError(null)
    setFieldErrors({})

    // Client-side check only for the field the task actually requires.
    const needsText = task !== 'generate'
    if (needsText && !form.text.trim()) {
      setFieldErrors({ text: 'Enter the text to work with' })
      return
    }
    if (task === 'generate' && !form.topic.trim()) {
      setFieldErrors({ topic: 'Enter a topic' })
      return
    }
    if (task === 'rewrite' && !form.instructions.trim()) {
      setFieldErrors({ instructions: 'Describe how it should be rewritten' })
      return
    }

    setIsSubmitting(true)
    setResult(null)
    try {
      const response = await runTask(task, form)
      setResult(response)
    } catch (caught) {
      setFieldErrors(caught.fieldErrors ?? {})
      setError({ text: friendlyError(caught), requestId: caught.requestId })
    } finally {
      setIsSubmitting(false)
    }
  }

  const activeTask = TASKS.find((item) => item.id === task)

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Content Agent</h1>
        <p className="mt-1 text-sm text-slate-500">
          Generate new content, or transform text you already have.
        </p>
      </header>

      <Card title="Task">
        <form onSubmit={handleSubmit} noValidate className="space-y-5">
          <Select
            label="What would you like to do?"
            value={task}
            onChange={(event) => changeTask(event.target.value)}
            options={TASKS.map(({ id, label }) => ({ value: id, label }))}
          />

          <TaskFields task={task} form={form} update={update} fieldErrors={fieldErrors} />

          {error && (
            <Alert variant="error" requestId={error.requestId}>
              {error.text}
            </Alert>
          )}

          <div className="flex flex-wrap gap-3">
            <Button type="submit" loading={isSubmitting}>
              {isSubmitting ? activeTask.busy : activeTask.label}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setForm(INITIAL_FORM)
                setResult(null)
                setError(null)
                setFieldErrors({})
              }}
              disabled={isSubmitting}
            >
              Clear
            </Button>
          </div>
        </form>
      </Card>

      <ContentResult task={task} result={result} isSubmitting={isSubmitting} />
    </div>
  )
}

function runTask(task, form) {
  switch (task) {
    case 'generate':
      return contentApi.generate({
        topic: form.topic.trim(),
        content_type: form.content_type,
        tone: form.tone,
        audience: form.audience,
        length: form.length,
        // Omitted when blank — the field is optional server-side.
        ...(form.additional_instructions.trim()
          ? { additional_instructions: form.additional_instructions.trim() }
          : {}),
      })
    case 'summarize':
      return contentApi.summarize(form.text, form.summary_type)
    case 'rewrite':
      return contentApi.rewrite(form.text, form.instructions)
    case 'tone':
      return contentApi.transformTone(form.text, form.target_tone)
    case 'audience':
      return contentApi.adaptAudience(form.text, form.target_audience)
    case 'format':
      return contentApi.transformFormat(form.text, form.format)
    case 'extract':
      return contentApi.extract(form.text)
    default:
      throw new Error(`Unknown task: ${task}`)
  }
}

function TaskFields({ task, form, update, fieldErrors }) {
  if (task === 'generate') {
    return (
      <>
        <TextInput
          label="Topic"
          required
          value={form.topic}
          onChange={update('topic')}
          error={fieldErrors.topic}
          placeholder="Artificial intelligence in education"
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Content type" value={form.content_type} onChange={update('content_type')} options={asOptions(CONTENT_TYPES)} />
          <Select label="Tone" value={form.tone} onChange={update('tone')} options={asOptions(TONES)} />
          <Select label="Audience" value={form.audience} onChange={update('audience')} options={asOptions(AUDIENCES)} />
          <Select label="Length" value={form.length} onChange={update('length')} options={asOptions(LENGTHS)} />
        </div>
        <TextArea
          label="Additional instructions"
          hint="Optional"
          rows={3}
          value={form.additional_instructions}
          onChange={update('additional_instructions')}
          error={fieldErrors.additional_instructions}
          placeholder="Use simple examples."
        />
      </>
    )
  }

  const sourceText = (
    <TextArea
      label="Source text"
      required
      rows={10}
      value={form.text}
      onChange={update('text')}
      error={fieldErrors.text}
      placeholder="Paste the text you want to work with…"
    />
  )

  return (
    <>
      {sourceText}
      {task === 'summarize' && (
        <Select label="Summary type" value={form.summary_type} onChange={update('summary_type')} options={asOptions(SUMMARY_TYPES)} />
      )}
      {task === 'rewrite' && (
        <TextInput
          label="Instructions"
          required
          value={form.instructions}
          onChange={update('instructions')}
          error={fieldErrors.instructions}
          placeholder="Make this clearer and more professional."
        />
      )}
      {task === 'tone' && (
        <Select label="Target tone" value={form.target_tone} onChange={update('target_tone')} options={asOptions(TONES)} />
      )}
      {task === 'audience' && (
        <Select label="Target audience" value={form.target_audience} onChange={update('target_audience')} options={asOptions(AUDIENCES)} />
      )}
      {task === 'format' && (
        <Select label="Target format" value={form.format} onChange={update('format')} options={asOptions(FORMATS)} />
      )}
    </>
  )
}

function ContentResult({ task, result, isSubmitting }) {
  if (isSubmitting) {
    return (
      <Card title="Result">
        <EmptyState icon="◌" title="Working…" description="The AI is processing your request." />
      </Card>
    )
  }

  if (!result) {
    return (
      <Card title="Result">
        <EmptyState
          title="No result yet"
          description="Choose a task, fill in the form and run it to see output here."
        />
      </Card>
    )
  }

  if (task === 'extract') {
    const sections = [
      ['Entities', result.entities],
      ['Key points', result.key_points],
      ['Facts', result.facts],
      ['Keywords', result.keywords],
    ]
    const hasAnything = sections.some(([, items]) => items?.length)

    return (
      <Card title="Extracted information">
        {hasAnything ? (
          <div className="space-y-5">
            {sections.map(([heading, items]) => (
              <div key={heading}>
                <h3 className="text-sm font-semibold text-slate-900">{heading}</h3>
                <div className="mt-2">
                  <BulletList
                    items={items}
                    empty={<p className="text-sm text-slate-400">None found in the source.</p>}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="Nothing extracted" description="The source contained no identifiable information." />
        )}
        <ResultMeta result={result} />
      </Card>
    )
  }

  return (
    <Card title="Result" actions={<CopyButton text={result.content} />}>
      <ProseBlock text={result.content} />
      <ResultMeta result={result} />
    </Card>
  )
}
