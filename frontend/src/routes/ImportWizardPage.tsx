import { useRef, useState, type DragEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { FileUp } from 'lucide-react';
import {
  soloApi,
  SoloLedgerApiError,
  type ImportPreviewDto,
  type MappingConfigDto,
} from '../api/client.js';
import { useCreateImport, useDemoSession } from '../api/hooks.js';
import { LedgerShell } from '../components/LedgerShell.js';
import { AlertBanner, Button } from '../components/UiPrimitives.js';

export function ImportWizardPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const { data: session } = useDemoSession();
  const accountId = session?.account?.id;
  const createImport = useCreateImport(accountId);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState<ImportPreviewDto | null>(null);
  const [mapping, setMapping] = useState<MappingConfigDto | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string>('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [duplicateImportId, setDuplicateImportId] = useState<string | null>(null);

  async function handleFileSelected(file: File | undefined) {
    if (!file) return;
    setErrorMsg(null);
    setDuplicateImportId(null);
    setUploading(true);
    try {
      const data = await soloApi.createImportPreview(file);
      setPreview(data);
      setMapping(data.suggestedMapping);
      setIdempotencyKey(`imp_${data.sha256.slice(0, 16)}_${Date.now()}`);
      setStep(2);
    } catch (err) {
      if (err instanceof SoloLedgerApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg('Failed to upload CSV preview.');
      }
    } finally {
      setUploading(false);
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    void handleFileSelected(file);
  }

  async function handleConfirmImport() {
    if (!preview || !mapping) return;
    setErrorMsg(null);
    setDuplicateImportId(null);
    try {
      const accepted = await createImport.mutateAsync({
        uploadToken: preview.uploadToken,
        mapping,
        idempotencyKey: idempotencyKey || `imp_${Date.now()}`,
      });
      navigate(`/imports/${accepted.jobId}`);
    } catch (err) {
      if (err instanceof SoloLedgerApiError) {
        setErrorMsg(err.message);
        const existingId = err.details?.existingImportId;
        if (err.code === 'DUPLICATE_IMPORT' && typeof existingId === 'string') {
          setDuplicateImportId(existingId);
        }
      } else {
        setErrorMsg('Failed to start import job.');
      }
    }
  }

  const ambiguousDate = mapping?.dateFormat === 'AMBIGUOUS_SLASH';

  return (
    <LedgerShell
      title="Import statement"
      subtitle="3-step CSV upload: 1. Choose file → 2. Map columns → 3. Confirm asynchronous job"
    >
      <div className="sl-import-grid">
        <div className="sl-card" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
          <ol
            aria-label="Import steps"
            style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', listStyle: 'none', margin: 0, padding: 0 }}
          >
            {([1, 2, 3] as const).map((s) => (
              <li
                key={s}
                aria-current={step === s ? 'step' : undefined}
                style={{
                  padding: '6px 12px',
                  borderRadius: '999px',
                  fontSize: '13px',
                  fontWeight: 600,
                  backgroundColor: step === s ? 'var(--accent-soft)' : 'var(--surface-muted)',
                  color: step === s ? 'var(--accent-hover)' : 'var(--muted)',
                  border: '1px solid var(--line)',
                }}
              >
                {s === 1 ? '1. Choose file' : s === 2 ? '2. Map columns' : '3. Confirm'}
              </li>
            ))}
          </ol>

          {errorMsg ? (
            <AlertBanner
              kind="danger"
              title="Import check failed"
              message={errorMsg}
              action={
                duplicateImportId ? (
                  <Link
                    to={`/imports/${duplicateImportId}`}
                    className="sl-btn-link sl-btn-link--secondary"
                  >
                    View existing import
                  </Link>
                ) : null
              }
            />
          ) : null}

          {step === 1 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={() => setDragActive(false)}
                onDrop={handleDrop}
                style={{
                  border: `2px dashed ${dragActive ? 'var(--accent)' : 'var(--line)'}`,
                  borderRadius: 'var(--r-card)',
                  backgroundColor: dragActive ? 'var(--accent-soft)' : 'var(--surface-muted)',
                  padding: '32px 20px',
                  textAlign: 'center',
                }}
              >
                <FileUp size={28} color="var(--accent)" aria-hidden="true" />
                <p style={{ margin: '10px 0 6px', fontWeight: 600 }}>
                  Drag and drop a UTF-8 `.csv` statement here, or choose a file
                </p>
                <p style={{ margin: '0 0 16px', fontSize: '13px', color: 'var(--muted)' }}>
                  Maximum 10 MB · Signed amounts or separate Debit/Credit columns · USD only
                </p>
                <input
                  ref={fileInputRef}
                  data-testid="csv-file-input"
                  type="file"
                  accept=".csv,text/csv"
                  aria-label="Choose CSV statement file"
                  onChange={(e) => void handleFileSelected(e.target.files?.[0])}
                  style={{ display: 'none' }}
                />
                <Button
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? 'Uploading preview...' : 'Choose CSV file'}
                </Button>
              </div>

              <div
                style={{
                  padding: '12px 14px',
                  borderRadius: 'var(--r-sm)',
                  border: '1px solid var(--line)',
                  backgroundColor: 'var(--surface)',
                  fontSize: '13px',
                  display: 'flex',
                  flexWrap: 'wrap',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '10px',
                }}
              >
                <span>Need synthetic test statements?</span>
                <span style={{ display: 'flex', gap: '14px' }}>
                  <a
                    href="/samples/smoke_5rows.csv"
                    download="smoke_5rows.csv"
                    style={{ color: 'var(--accent)', fontWeight: 600 }}
                  >
                    Download 5-row smoke CSV
                  </a>
                  <a
                    href="/samples/sample_statement.csv"
                    download="sample_statement.csv"
                    style={{ color: 'var(--accent)', fontWeight: 600 }}
                  >
                    Download 90-row synthetic CSV
                  </a>
                </span>
              </div>
            </div>
          ) : null}

          {step === 2 && preview && mapping ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              {ambiguousDate ? (
                <AlertBanner
                  kind="warning"
                  title="Ambiguous slash dates detected"
                  message="Choose whether slash dates in this CSV use MM/DD/YYYY (US) or DD/MM/YYYY (EU) before confirming."
                />
              ) : null}

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '12px' }}>
                <label style={{ fontSize: '13px', fontWeight: 600 }}>
                  Posted date column
                  <select
                    value={mapping.postedDateColumn}
                    onChange={(e) => setMapping({ ...mapping, postedDateColumn: e.target.value })}
                    style={{ width: '100%', minHeight: '40px', marginTop: '4px', padding: '6px 8px' }}
                  >
                    {preview.headers.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>

                <label style={{ fontSize: '13px', fontWeight: 600 }}>
                  Description / Merchant column
                  <select
                    value={mapping.descriptionColumn}
                    onChange={(e) => setMapping({ ...mapping, descriptionColumn: e.target.value })}
                    style={{ width: '100%', minHeight: '40px', marginTop: '4px', padding: '6px 8px' }}
                  >
                    {preview.headers.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>

                <label style={{ fontSize: '13px', fontWeight: 600 }}>
                  Amount representation
                  <select
                    value={mapping.amountMode}
                    onChange={(e) =>
                      setMapping({
                        ...mapping,
                        amountMode: e.target.value as 'DEBIT_CREDIT' | 'SIGNED_AMOUNT',
                      })
                    }
                    style={{ width: '100%', minHeight: '40px', marginTop: '4px', padding: '6px 8px' }}
                  >
                    <option value="SIGNED_AMOUNT">Signed amount (`-` expense / `+` refund/income)</option>
                    <option value="DEBIT_CREDIT">Separate Debit & Credit columns</option>
                  </select>
                </label>

                <label style={{ fontSize: '13px', fontWeight: 600 }}>
                  Date format
                  <select
                    aria-label="Date format"
                    value={mapping.dateFormat}
                    onChange={(e) => setMapping({ ...mapping, dateFormat: e.target.value })}
                    style={{ width: '100%', minHeight: '40px', marginTop: '4px', padding: '6px 8px' }}
                  >
                    {ambiguousDate ? <option value="AMBIGUOUS_SLASH">Select format...</option> : null}
                    <option value="%Y-%m-%d">YYYY-MM-DD (ISO)</option>
                    <option value="%m/%d/%Y">MM/DD/YYYY (US)</option>
                    <option value="%d/%m/%Y">DD/MM/YYYY (EU)</option>
                  </select>
                </label>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                <Button variant="secondary" onClick={() => setStep(1)}>
                  Back to file picker
                </Button>
                <Button disabled={ambiguousDate} onClick={() => setStep(3)}>
                  Continue to confirm
                </Button>
              </div>
            </div>
          ) : null}

          {step === 3 && preview && mapping ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              <div style={{ fontSize: '14px' }}>
                <div>
                  <strong>File:</strong> {preview.fileName}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                  SHA-256: <code>{preview.sha256.slice(0, 16)}...</code> · Mode:{' '}
                  <code>{mapping.amountMode}</code> · Date format: <code>{mapping.dateFormat}</code>
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                <Button variant="secondary" onClick={() => setStep(2)}>
                  Edit mapping
                </Button>
                <Button
                  data-testid="confirm-import-btn"
                  disabled={createImport.isPending}
                  onClick={() => void handleConfirmImport()}
                >
                  {createImport.isPending ? 'Queuing job...' : 'Start asynchronous import'}
                </Button>
              </div>
            </div>
          ) : null}
        </div>

        <aside className="sl-card" aria-label="Normalized upload preview">
          <h2 style={{ margin: '0 0 12px', fontSize: '17px', fontWeight: 600 }}>
            Preview & sign rules
          </h2>
          {preview ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ fontSize: '13px', color: 'var(--muted)' }}>
                First {preview.previewRows.length} rows of <strong>{preview.fileName}</strong>:
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--line)', textAlign: 'left' }}>
                      {preview.headers.slice(0, 4).map((h) => (
                        <th key={h} style={{ padding: '6px 4px' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.previewRows.map((row, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid var(--line)' }}>
                        {preview.headers.slice(0, 4).map((h) => (
                          <td key={h} style={{ padding: '6px 4px' }}>
                            {row[h] ?? ''}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--muted)' }}>
              Sign convention: expenses are stored negative (<code>-42.85</code>) and client income or refunds are stored positive (<code>+150.00</code>). Only valid USD transactions enter ledger totals; invalid rows remain quarantined on the import job.
            </p>
          )}
        </aside>
      </div>
    </LedgerShell>
  );
}

