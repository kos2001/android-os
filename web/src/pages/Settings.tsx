import { KeyRound, Languages, Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '../components/layout'
import { useToast } from '../components/ui/overlay'
import { Button, Card, CardHeader, Field, Input, KeyValue, Segmented } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { api, getApiKey, setApiKey } from '../lib/api'
import { useAsync, useTheme } from '../lib/hooks'
import { useLang, useT, type Lang } from '../lib/i18n'

export default function SettingsPage() {
  const toast = useToast()
  const t = useT()
  const [theme, setTheme] = useTheme()
  const [lang, setLang] = useLang()
  const [key, setKey] = useState(getApiKey())
  const [testing, setTesting] = useState(false)
  const health = useAsync(() => api.health(), [])
  const overview = useAsync(() => api.overview(), [])

  const save = async () => {
    setApiKey(key.trim())
    setTesting(true)
    try {
      await api.platforms()
      toast({ kind: 'success', title: key.trim() ? t('API 키 확인됨', 'API key verified') : t('API 키를 지웠습니다', 'API key cleared') })
    } catch (e) {
      toast({ kind: 'error', title: t('API 키로 요청 실패', 'Request with API key failed'), description: (e as Error).message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <>
      <PageHeader title={t('설정', 'Settings')} description={t('이 브라우저에만 저장됩니다.', 'Saved in this browser only.')} />
      <div className="grid max-w-3xl gap-4">
        <Card>
          <CardHeader title={t('API 키', 'API key')} description={t('ANDROID_OS_API_KEYS 에 등록된 키. 역할에 따라 사용할 수 있는 기능이 달라집니다.', 'A key registered in ANDROID_OS_API_KEYS. Available features depend on its role.')} />
          <div className="flex items-end gap-2 p-4">
            <Field label={t('Bearer 키', 'Bearer key')} className="flex-1" hint={overview.data?.dev_mode ? t('서버가 개발 모드라 키 없이도 동작합니다', 'Server is in dev mode, so it works without a key') : undefined}>
              <Input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" placeholder={t('키 입력', 'Enter key')} />
            </Field>
            <Button variant="primary" icon={<KeyRound className="size-3.5" />} loading={testing} onClick={save}>{t('저장 후 확인', 'Save and verify')}</Button>
          </div>
        </Card>
        <Card>
          <CardHeader title={t('테마', 'Theme')} />
          <div className="p-4">
            <Segmented value={theme} onChange={setTheme} items={[
              { value: 'system', label: <span className="flex items-center gap-1.5"><Monitor className="size-3.5" />{t('시스템', 'System')}</span> },
              { value: 'light', label: <span className="flex items-center gap-1.5"><Sun className="size-3.5" />{t('라이트', 'Light')}</span> },
              { value: 'dark', label: <span className="flex items-center gap-1.5"><Moon className="size-3.5" />{t('다크', 'Dark')}</span> },
            ]} />
          </div>
        </Card>
        <Card>
          <CardHeader title={t('언어', 'Language')} />
          <div className="p-4">
            <Segmented<Lang> value={lang} onChange={setLang} items={[
              { value: 'ko', label: <span className="flex items-center gap-1.5"><Languages className="size-3.5" />한국어</span> },
              { value: 'en', label: <span className="flex items-center gap-1.5"><Languages className="size-3.5" />English</span> },
            ]} />
          </div>
        </Card>
        <Card>
          <CardHeader title={t('서버', 'Server')} />
          <div className="p-4">
            <KeyValue items={[
              [t('상태', 'Status'), health.data ? <Badge tone="good">{health.data.status}</Badge> : health.error ? <Badge tone="critical">{t('연결 실패', 'Connection failed')}</Badge> : '…'],
              [t('버전', 'Version'), health.data?.version ?? '—'],
              [t('지식베이스', 'Knowledge base'), health.data?.kb_version ?? '—'],
              [t('모드', 'Mode'), overview.data ? (overview.data.dev_mode ? <Badge tone="warning">{t('개발 모드 · 인증 없음', 'Dev mode · no auth')}</Badge> : <Badge tone="good">{t('운영 모드', 'Production mode')}</Badge>) : '—'],
              [t('API 문서', 'API docs'), <a href="/docs" target="_blank" rel="noreferrer" className="text-accent-ink hover:underline">/docs (OpenAPI)</a>],
            ]} />
          </div>
        </Card>
      </div>
    </>
  )
}
