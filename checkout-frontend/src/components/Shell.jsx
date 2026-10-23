// Header/footer markup shared by both views (same structure as the original pages).

export function Header({ brand }) {
  return (
    <header>
      {brand.website_url ? (
        <a className="wordmark" href={brand.website_url}>
          {brand.logo_url && <img id="brand-logo" src={brand.logo_url} alt="" />}
          <span id="brand-name">{brand.name}</span>
        </a>
      ) : (
        <span className="wordmark">
          {brand.logo_url && <img id="brand-logo" src={brand.logo_url} alt="" />}
          <span id="brand-name">{brand.name}</span>
        </span>
      )}
      <span className="secure">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="5" y="10" width="14" height="11" rx="3" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3" />
        </svg>
        Secure checkout
      </span>
    </header>
  );
}

export function Footer({ brand }) {
  return (
    <footer>
      <span className="footer-security">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="3" />
          <path d="M3 10h18M7 15h3" />
        </svg>
        Secure payments powered by Stripe
      </span>
      <span id="brand-support">{[brand.support_email, brand.support_phone].filter(Boolean).join(' · ')}</span>
    </footer>
  );
}

export const TEST_NOTICE = 'Live payment test: your card will be charged. No medication will be shipped.';
