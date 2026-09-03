// Branded transactional email shells. Email clients are hostile terrain:
// table layout, inline styles, system fonts, no SVG. One shell, many bodies.

const PETROL = '#15242c'
const CARD = '#1e3038'
const AMBER = '#eda63a'
const MIST = '#93a6ab'
const PAPER = '#f4f6f3'
const INK = '#1c2622'

export function emailShell(opts: {
  preheader: string
  bodyHtml: string
}): string {
  return `<!doctype html>
<html>
<body style="margin:0;padding:0;background:${PAPER};font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif">
  <div style="display:none;max-height:0;overflow:hidden">${opts.preheader}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${PAPER}">
    <tr><td align="center" style="padding:32px 16px">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%">
        <tr><td style="background:${PETROL};border-radius:8px 8px 0 0;padding:20px 28px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="font-size:18px;font-weight:700;letter-spacing:-0.01em;color:#f2f6f6">
              shadow<span style="color:${AMBER}">price</span>
            </td>
            <td align="right" style="font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:${MIST}">
              ERCOT CRR Analytics
            </td>
          </tr></table>
        </td></tr>
        <tr><td style="background:#ffffff;border:1px solid #d5dcd4;border-top:none;padding:28px">
          ${opts.bodyHtml}
        </td></tr>
        <tr><td style="background:${CARD};border-radius:0 0 8px 8px;padding:18px 28px">
          <div style="font-size:13px;color:#dbe4e6;font-weight:600">— The Shadowprice team</div>
          <div style="font-size:11px;color:${MIST};margin-top:6px;line-height:1.5">
            Shadowprice · pricing discipline for ERCOT congestion revenue rights<br>
            All analytics derive from public ERCOT data. We hold no CRR positions.
          </div>
        </td></tr>
        <tr><td style="padding:14px 28px;font-size:11px;color:#8a948f;line-height:1.5">
          You received this because this address is the registered ERCOT contact
          for the account named above. If the request was not authorized by you,
          no action is needed — nothing is shared without this confirmation.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`
}

export function claimVerificationEmail(opts: {
  code: string
  verifyUrl: string
}): { html: string; text: string } {
  const bodyHtml = `
    <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#8a948f;margin-bottom:10px">
      Access request
    </div>
    <div style="font-size:19px;font-weight:700;color:${INK};margin-bottom:14px">
      Confirm access to CRR account ${opts.code}
    </div>
    <div style="font-size:14px;line-height:1.6;color:#3d4a45;margin-bottom:22px">
      Someone signed up on Shadowprice and requested access to the book of CRR
      account holder <b>${opts.code}</b>, whose registered contact address this is.
      If that request is yours — or authorized by you — confirm it below.
    </div>
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:22px"><tr>
      <td style="background:${AMBER};border-radius:6px">
        <a href="${opts.verifyUrl}"
           style="display:inline-block;padding:12px 26px;font-size:14px;font-weight:700;color:${PETROL};text-decoration:none">
          Confirm access
        </a>
      </td>
    </tr></table>
    <div style="font-size:12px;line-height:1.6;color:#8a948f">
      The link expires in 7 days. If the button doesn't work, open:<br>
      <a href="${opts.verifyUrl}" style="color:#b45309;word-break:break-all">${opts.verifyUrl}</a>
    </div>`
  const text =
    `Confirm access to CRR account ${opts.code} on Shadowprice\n\n` +
    `Someone signed up on Shadowprice and requested access to the book of CRR ` +
    `account holder ${opts.code}, whose registered contact address this is.\n\n` +
    `If that request is yours (or authorized by you), open:\n${opts.verifyUrl}\n\n` +
    `If not, ignore this email — nothing is shown without this confirmation. ` +
    `The link expires in 7 days.\n\n— The Shadowprice team`
  return { html: emailShell({ preheader: `Confirm access to CRR account ${opts.code}`, bodyHtml }), text }
}
