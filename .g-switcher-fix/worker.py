from pathlib import Path
import hashlib,json,os,subprocess
root=Path.cwd(); me=Path(__file__).resolve()
assert hashlib.sha256(me.read_bytes()).hexdigest()==os.environ['CDC_PAYLOAD_SHA256'], 'Pinned worker/payload drift'
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='06e1498e36dc497b41eaa3fd294c733db65fd943'
p=root/'src/windows_runtime/ui/settings_dialog.rs';text=p.read_text();old='UiRect::new(24, 472, 852, 142)';assert text.count(old)==1
# Lower controls end at614, exactly the old group bottom. Give them12px of inner clearance.
p.write_text(text.replace(old,'UiRect::new(24, 472, 852, 154)'))
report={'schema':'g-switcher-word-native-evidence/v1','word_version':'16.0.5569.1000','legacy_set_value_hresult':'0x80004001','nativeom_accessible_hresult':'0x00000000','native_range_writer_succeeded':True,'post_matches_replacement':True,'terminal_paragraph_preserved':True,'product_word_adapter_implemented':False,'formatting_tested':False,'undo_tested':False,'evidence':['user:GSwitcher-Word-Writer-20261007-142509-8ae726ec.json','user:GSwitcher-Word-Range-20261007-150533-16aa995f.json'],'source_base':'06e1498e36dc497b41eaa3fd294c733db65fd943','next_action':'Implement Word-specific native range adapter with format/Undo preservation; test full runtime and installed Word before compatibility claim.'}
p=root/'docs/work-status/word-native-evidence-2026-10-07.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,indent=2)+'\n')
plan='''# Word native adapter implementation plan

Confirmed installed Word16.0.5569.1000 returns E_NOTIMPL for Legacy.SetValue, while AccessibleObjectFromWindow(OBJID_NATIVEOM, IID_IDispatch), exact native Range.Duplicate/SetRange(0,6) and Range.Text replacement succeed. This is provider evidence, not full product acceptance.

## Requirements

- Add src/windows_runtime/word_native.rs and select it for _WwG before modern Legacy/Value routing in selection.rs; no fallback to whole-value Legacy.SetValue for Word.
- Bind every operation to focused HWND/PID, UIA password/enabled/focusable/RuntimeId checks and native Window.Hwnd root. Bind the fixed Document identity; use Window.Selection, never global ActiveDocument/Selection.
- Keep native story positions separate from UIA scalar-prefix offsets. Support main text story first; refuse unverifiable offsets, protected/read-only documents, tracked revisions and non-contiguous selections.
- Read and replace bounded exact expected ranges through independent native duplicates. Exclude Word's final paragraph from a full-document selection without removing internal paragraph/control characters.
- Equal-length keyboard conversion must preserve per-character formatting. Use range-local character operations and one native UndoRecord; refuse unsafe character-position transformations. Never reset the whole document or use clipboard/SendInput.
- Revalidate focus, document, selection and expected text immediately before writing. Verify exact resulting text/caret; constrain any rollback to the exact observed state. Release COM/VARIANT/BSTR resources on success and errors; do not log document text.

## Execution

- [ ] Add and run failing tests for native-coordinate suffix planning, terminal paragraph exclusion, surrogate boundaries and unsupported/changed contexts.
- [ ] Implement native IDispatch/VARIANT ownership and guarded Word context; use existing windows bindings where possible.
- [ ] Wire selected text, caret snapshot, suffix/range mutation and Undo through the current selection API; Word adapter uses native UTF16 coordinates consistently.
- [ ] Review complete writer/failure behavior, then run exact-candidate Windows Rust CI.
- [ ] In installed Word validate Auto/F12/F9, multiple paragraphs, mixed formatting, Unicode, native Ctrl+Z and G-switcher Undo. Check Edge/Chrome/Telegram/Notepad regressions and actual versions.

The same branch contains only a settings group clearance correction plus this evidence/plan so far. Word runtime is not repaired by this preparation commit. Draft PR28 and public-promotion/manual gates remain unchanged; no scheduler mutation.
'''
p=root/'docs/work-status/word-native-plan-2026-10-07.md';p.write_text(plan)
subprocess.run(['git','config','user.name','G-switcher managed executor'],check=True)
subprocess.run(['git','config','user.email','g-switcher@example.invalid'],check=True)
paths=['src/windows_runtime/ui/settings_dialog.rs','docs/work-status/word-native-evidence-2026-10-07.json','docs/work-status/word-native-plan-2026-10-07.md']
changed=subprocess.check_output(['git','status','--porcelain'],text=True);print(changed)
subprocess.run(['git','add','--',*paths],check=True)
subprocess.run(['git','diff','--cached','--check'],check=True)
subprocess.run(['git','commit','-m','[skip ci] fix settings group clearance; record proven Word native writer'],check=True)
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
evidence=Path(os.environ['CDC_WORKER_EVIDENCE_ROOT']);evidence.mkdir(parents=True,exist_ok=True)
(evidence/'result.json').write_text(json.dumps({'source_base':report['source_base'],'result_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'word_fix_implemented':False,'changed_paths':paths,'validation':'git diff --cached --check; exact replacement count; native Windows gate pending'},indent=2)+'\n')
