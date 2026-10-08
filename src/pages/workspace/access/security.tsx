/**
 * Sign-in & MFA — the operator's own second factors.
 *
 * Exists because TOTP enrolment is not an admin operation. Cognito's
 * `AssociateSoftwareToken` does not evaluate IAM policies, so it can only be
 * authorized with the signed-in user's own access token; attempting it from the
 * admin side returns "User does not have delivery config set to turn on
 * SOFTWARE_TOKEN_MFA".
 *
 * WHAT THE POOL ACTUALLY ALLOWS, measured rather than assumed. This docblock used
 * to claim "Pool-level TOTP is on, email MFA is on and SMS is configured". That is
 * false. `MfaConfiguration` reads `OFF` on BOTH user pools —
 * `us-east-1_cSx0RHCIR` (staff) and `us-east-1_46ULYuukt` (the public customer OTP
 * pool) — so no second factor is enforced for anybody today. Source:
 * docs/execution/aws-inventory.json -> cognito.user_pools[].mfa_configuration.
 *
 * So read this page as where a person enrols their OWN authenticator once the pool
 * permits it, not as evidence that a second factor is in force. Turning MFA on at
 * the POOL is a separate, owner-gated change, and this edit does not make it: it
 * corrects the record only. Any reader relying on the old sentence to conclude the
 * admin-MFA target was met was reading a claim nothing had verified.
 *
 * Styled to the PUBLIC contract, as asked: the 1300px measure, the 1.04
 * line-height section heading with -1.875px tracking, the single 20px body level,
 * and the white/#fafafa section rhythm. Values are from
 * .kiro/steering/grahak-os-design.md, not approximated.
 *
 * `sec-` prefix rather than `page-` or `section-`: four globally imported
 * stylesheets declare generic names unscoped, and styled-jsx does not shield a
 * page from those. PageHeader is deliberately NOT used here — it renders
 * `.page-header`/`.page-title`, which Pages.css styles on the inner ladder, so it
 * would contradict the public type ladder this page is meant to match.
 */
import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import TotpSetup from '../../../components/security/TotpSetup';

interface PageProps { signOut?: () => void; user?: any; }

const SecurityPage: React.FC<PageProps> = ( { signOut, user } ) => (
  <Layout user={ user } onSignOut={ signOut }>
    <SEO
      title="Sign-in & MFA"
      description="Manage the second factors on your own WECARE.DIGITAL account."
      noindex
    />
    <div className="sec-page">
      <div className="sec-inner">
        <header className="sec-head">
          <h1 className="sec-h1">Sign-in &amp; MFA</h1>
          <p className="sec-sub">
            Second factors for your own account. Email codes are on and your
            verified mobile is registered as a fallback.
          </p>
        </header>
        <TotpSetup />
      </div>
      <style jsx>{`
        /* #fafafa is the contract's alternate band. The card sits white on it,
           which is the same figure/ground pair the public sections use. */
        .sec-page{
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background:#fafafa;min-height:100%;padding:60px 0;box-sizing:border-box;
        }
        /* 1300px with 24px padding — .pp-inner's measure. */
        .sec-inner{max-width:1300px;margin:0 auto;padding:0 24px;box-sizing:border-box}
        .sec-head{margin:0 0 32px}
        /* Section-h2 rung: 700 is HEAVIER than the hero's 600. That inversion is
           the contract's and is intentional — do not "correct" it. */
        .sec-h1{
          font-size:clamp(32px,4.2vw,54px);font-weight:700;line-height:1.04;
          letter-spacing:-1.875px;color:rgba(0,0,0,.95);margin:0 0 14px;
        }
        /* The single body level. */
        .sec-sub{
          font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
          color:rgba(0,0,0,.898);margin:0;max-width:560px;
        }
        @media(max-width:767px){
          .sec-page{padding:40px 0}
          .sec-inner{padding:0 20px}
          .sec-h1{letter-spacing:-1.2px;line-height:1.1}
          .sec-sub{font-size:17px}
        }
        @media(max-width:480px){
          .sec-inner{padding:0 16px}
          .sec-h1{letter-spacing:-.8px}
        }
      `}</style>
    </div>
  </Layout>
);

export default SecurityPage;
