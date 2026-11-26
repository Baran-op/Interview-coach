import { useCallback, useEffect, useLayoutEffect, useRef, type TextareaHTMLAttributes } from 'react'

/**
 * A <textarea> that grows to fit its text (`rows` is the minimum height). Re-measures when the text changes and
 * when its width changes, e.g. when a closed <details> around it opens.
 */
export default function AutoTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null)

  const fit = useCallback(() => {
    const el = ref.current
    if (!el || el.offsetWidth === 0) return // hidden: measured again once it shows
    el.style.height = 'auto'
    const border = el.offsetHeight - el.clientHeight
    el.style.height = `${el.scrollHeight + border}px`
  }, [])

  useLayoutEffect(fit, [fit, props.value])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    let width = el.offsetWidth
    const ro = new ResizeObserver(() => {
      if (el.offsetWidth !== width) {
        width = el.offsetWidth
        fit()
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [fit])

  return <textarea {...props} ref={ref} className={`autosize ${props.className ?? ''}`.trim()} />
}
