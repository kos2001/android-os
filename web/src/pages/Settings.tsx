import { KeyRound, Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '../components/layout'
import { useToast } from '../components/ui/overlay'
import { Button, Card, CardHeader, Field, Input, KeyValue, Segmented } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { api, getApiKey, setApiKey } from '../lib/api'
import { useAsync, useTheme } from '../lib/hooks'

export default function SettingsPage() {
  const toast = useToast()
  const [theme, setTheme] = useTheme()
  const [key, setKey] = useState(getApiKey())
  const [testing, setTesting] = useState(false)
  const health = useAsync(() => api.health(), [])
  const overview = useAsync(() => api.overview(), [])

  const save = async () => {
    setApiKey(key.trim())
    setTesting(true)
    try {
      await api.platforms()
      toast({ kind: 'success', title: key.trim() ? 'API 키 확인됨' : 'API 키를 지웠습니다' })
    } catch (e) {
      toast({ kind: 'error', title: 'API 키로 요청 실패', description: (e as Error).message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <>
      <PageHeader title="설정" description="이 브라우저에만 저장됩니다." />
      <div className="grid max-w-3xl gap-4">
        <Card>
          <CardHeader title="API 키" description="ANDROID_OS_API_KEYS 에 등록된 키. 역할에 따라 사용할 수 있는 기능이 달라집니다." />
          <div className="flex items-end gap-2 p-4">
            <Field label="Bearer 키" className="flex-1" hint={overview.data?.dev_mode ? '서버가 개발 모드라 키 없이도 동작합니다' : undefined}>
              <Input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" placeholder="키 입력" />
            </Field>
            <Button variant="primary" icon={<KeyRound className="size-3.5" />} loading={testing} onClick={save}>저장 후 확인</Button>
          </div>
        </Card>
        <Card>
          <CardHeader title="테마" />
          <div className="p-4">
            <Segmented value={theme} onChange={setTheme} items={[
              { value: 'system', label: <span className="flex items-center gap-1.5"><Monitor className="size-3.5" />시스템</span> },
              { value: 'light', label: <span className="flex items-center gap-1.5"><Sun className="size-3.5" />라이트</span> },
              { value: 'dark', label: <span className="flex items-center gap-1.5"><Moon className="size-3.5" />다크</span> },
            ]} />
          </div>
        </Card>
        <Card>
          <CardHeader title="서버" />
          <div className="p-4">
            <KeyValue items={[
              ['상태', health.data ? <Badge tone="good">{health.data.status}</Badge> : health.error ? <Badge tone="critical">연결 실패</Badge> : '…'],
              ['버전', health.data?.version ?? '—'],
              ['지식베이스', health.data?.kb_version ?? '—'],
              ['모드', overview.data ? (overview.data.dev_mode ? <Badge tone="warning">개발 모드 · 인증 없음</Badge> : <Badge tone="good">운영 모드</Badge>) : '—'],
              ['API 문서', <a href="/docs" target="_blank" rel="noreferrer" className="text-accent-ink hover:underline">/docs (OpenAPI)</a>],
            ]} />
          </div>
        </Card>
      </div>
    </>
  )
}
