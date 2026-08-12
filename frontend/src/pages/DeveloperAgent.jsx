import { useState } from 'react'

import * as developerApi from '../api/developer'
import {
  Alert,
  Button,
  Card,
  CheckboxGroup,
  Select,
  TextArea,
  TextInput,
} from '../components/common'
import DeveloperResult from '../components/developer/DeveloperResult'
import { friendlyError, humanise } from '../utils/errorMessages'

/**
 * The language field is a free-text input, not a dropdown, because the
 * backend validates it as a constrained string rather than an enum — Elixir
 * and C++ are accepted even though they are not in the common list. The
 * datalist offers suggestions without restricting the value.
 */
const COMMON_LANGUAGES = [
  'python', 'javascript', 'typescript', 'java', 'c', 'cpp', 'csharp', 'go',
  'rust', 'php', 'ruby', 'kotlin', 'swift', 'sql', 'html', 'css', 'bash',
]

// Backend enums, mirrored exactly.
const REVIEW_FOCUS = [
  'bugs', 'security', 'performance', 'readability', 'maintainability',
  'error_handling', 'edge_cases',
]
const DOCUMENTATION_TYPES = ['function', 'module', 'api', 'readme', 'technical']

const TASKS = [
  { id: 'generate', label: 'Generate code', busy: 'Generating…', needsCode: false },
  { id: 'explain', label: 'Explain code', busy: 'Explaining…', needsCode: true },
  { id: 'review', label: 'Review code', busy: 'Reviewing…', needsCode: true },
  { id: 'refactor', label: 'Refactor code', busy: 'Refactoring…', needsCode: true },
  { id: 'tests', label: 'Generate tests', busy: 'Generating tests…', needsCode: true },
  { id: 'debug', label: 'Debug a problem', busy: 'Analysing…', needsCode: true },
  { id: 'document', label: 'Generate documentation', busy: 'Documenting…', needsCode: true },
]

const INITIAL_FORM = {
  language: 'python',
  code: '',
  description: '',
  requirements: '',
  goals: '',
  framework: '',
  errorMessage: '',
  context: '',
  documentationType: 'function',
}

/** Multi-line textarea → array, dropping blanks. The backend caps at 20 items. */
function toList(value) {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 20)
}

export default function DeveloperAgent() {
  const [task, setTask] = useState('explain')
  const [form, setForm] = useState(INITIAL_FORM)
  const [reviewFocus, setReviewFocus] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)

  const activeTask = TASKS.find((item) => item.id === task)

  function update(field) {
    return (event) => setForm((prev) => ({ ...prev, [field]: event.target.value }))
  }

  function changeTask(nextTask) {
    setTask(nextTask)
    setResult(null)
    setError(null)
    setFieldErrors({})
  }

  function toggleFocus(value) {
    setReviewFocus((prev) =>
      prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value],
    )
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (isSubmitting) return

    setError(null)
    setFieldErrors({})

    const errors = {}
    if (!form.language.trim()) errors.language = 'Enter a language'
    if (activeTask.needsCode && !form.code.trim()) errors.code = 'Paste some code'
    if (task === 'generate' && !form.description.trim()) {
      errors.description = 'Describe what the code should do'
    }
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors)
      return
    }

    setIsSubmitting(true)
    setResult(null)
    try {
      setResult(await runTask(task, form, reviewFocus))
    } catch (caught) {
      setFieldErrors(caught.fieldErrors ?? {})
      setError(friendlyError(caught))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Developer Agent</h1>
        <p className="mt-1 text-sm text-slate-500">
          Static analysis only — your code is never executed.
        </p>
      </header>

      <Card title="Task">
        <form onSubmit={handleSubmit} noValidate className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="What would you like to do?"
              value={task}
              onChange={(event) => changeTask(event.target.value)}
              options={TASKS.map(({ id, label }) => ({ value: id, label }))}
            />
            <div>
              <TextInput
                label="Language"
                required
                list="language-suggestions"
                value={form.language}
                onChange={update('language')}
                error={fieldErrors.language}
                placeholder="python"
              />
              <datalist id="language-suggestions">
                {COMMON_LANGUAGES.map((language) => (
                  <option key={language} value={language} />
                ))}
              </datalist>
            </div>
          </div>

          {task === 'generate' ? (
            <>
              <TextArea
                label="What should the code do?"
                required
                rows={4}
                value={form.description}
                onChange={update('description')}
                error={fieldErrors.description}
                placeholder="Create a function that checks whether a string is a palindrome."
              />
              <TextArea
                label="Requirements"
                hint="Optional — one per line"
                rows={4}
                value={form.requirements}
                onChange={update('requirements')}
                placeholder={'Use a clean function\nHandle empty strings'}
              />
            </>
          ) : (
            <TextArea
              label="Code"
              required
              mono
              rows={14}
              value={form.code}
              onChange={update('code')}
              error={fieldErrors.code}
              placeholder="Paste your code here…"
              spellCheck={false}
            />
          )}

          {task === 'review' && (
            <CheckboxGroup
              legend="Focus areas (optional)"
              options={REVIEW_FOCUS.map((value) => ({ value, label: humanise(value) }))}
              selected={reviewFocus}
              onToggle={toggleFocus}
            />
          )}

          {task === 'refactor' && (
            <TextArea
              label="Refactoring goals"
              hint="Optional — one per line"
              rows={3}
              value={form.goals}
              onChange={update('goals')}
              placeholder={'Improve readability\nRemove duplication'}
            />
          )}

          {task === 'tests' && (
            <TextInput
              label="Test framework"
              hint="Optional — leave blank to let the agent choose"
              value={form.framework}
              onChange={update('framework')}
              placeholder="pytest"
            />
          )}

          {task === 'debug' && (
            <>
              <TextArea
                label="Error message or stack trace"
                hint="Optional, but greatly improves the diagnosis"
                mono
                rows={4}
                value={form.errorMessage}
                onChange={update('errorMessage')}
                placeholder="IndexError: list index out of range"
              />
              <TextArea
                label="When does it happen?"
                hint="Optional"
                rows={3}
                value={form.context}
                onChange={update('context')}
                placeholder="Only when the input list is empty."
              />
            </>
          )}

          {task === 'document' && (
            <Select
              label="Documentation type"
              value={form.documentationType}
              onChange={update('documentationType')}
              options={DOCUMENTATION_TYPES.map((value) => ({
                value,
                label: humanise(value),
              }))}
            />
          )}

          {error && <Alert variant="error">{error}</Alert>}

          <div className="flex flex-wrap gap-3">
            <Button type="submit" loading={isSubmitting}>
              {isSubmitting ? activeTask.busy : activeTask.label}
            </Button>
            <Button
              variant="secondary"
              disabled={isSubmitting}
              onClick={() => {
                setForm(INITIAL_FORM)
                setReviewFocus([])
                setResult(null)
                setError(null)
                setFieldErrors({})
              }}
            >
              Clear
            </Button>
          </div>
        </form>
      </Card>

      <DeveloperResult task={task} result={result} isSubmitting={isSubmitting} />
    </div>
  )
}

function runTask(task, form, reviewFocus) {
  const language = form.language.trim()
  const code = form.code

  switch (task) {
    case 'generate':
      return developerApi.generateCode({
        language,
        description: form.description.trim(),
        requirements: toList(form.requirements),
      })
    case 'explain':
      return developerApi.explainCode({ language, code })
    case 'review':
      return developerApi.reviewCode({ language, code, reviewFocus })
    case 'refactor':
      return developerApi.refactorCode({ language, code, goals: toList(form.goals) })
    case 'tests':
      return developerApi.generateTests({ language, code, framework: form.framework.trim() })
    case 'debug':
      return developerApi.analyseBug({
        language,
        code,
        errorMessage: form.errorMessage.trim(),
        context: form.context.trim(),
      })
    case 'document':
      return developerApi.generateDocumentation({
        language,
        code,
        documentationType: form.documentationType,
      })
    default:
      throw new Error(`Unknown task: ${task}`)
  }
}
