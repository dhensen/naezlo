import { APP_NAME } from '../config'
import logo from '../assets/logo.png'
import mark from '../assets/logo-mark.png'

interface LogoProps {
  /** The height, and anything else about its place: `h-7`. The width follows. */
  className: string
  /** Only the mark below `sm`, where the top bar has no room for the word. */
  markOnPhone?: boolean
  /** Next to a text that already says the name: no name of its own. */
  decorative?: boolean
}

/** The logo: the mark and the name as one image, named after the product for a screen reader. */
export function Logo({ className, markOnPhone = false, decorative = false }: LogoProps) {
  const alt = decorative ? '' : APP_NAME
  if (!markOnPhone) {
    return <img src={logo} alt={alt} className={`w-auto ${className}`} />
  }
  // One image for both widths: the browser picks the source.
  return (
    <picture>
      <source media="(min-width: 640px)" srcSet={logo} />
      <img src={mark} alt={alt} className={`w-auto ${className}`} />
    </picture>
  )
}
