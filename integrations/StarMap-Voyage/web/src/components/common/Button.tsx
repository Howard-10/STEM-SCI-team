import type { ButtonHTMLAttributes, PropsWithChildren } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  fullWidth?: boolean
}

const variantStyles: Record<Variant, string> = {
  primary:
    'bg-indigo-600 text-white shadow-sm shadow-indigo-200 hover:bg-indigo-700 focus-visible:outline-indigo-500 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2',
  secondary:
    'border border-indigo-200 bg-white text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50 focus-visible:outline-indigo-500 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2',
  ghost:
    'bg-transparent text-indigo-600 hover:bg-indigo-50 hover:text-indigo-700 focus-visible:outline-indigo-500 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2',
}

function Button({
  children,
  className = '',
  fullWidth = false,
  type = 'button',
  variant = 'primary',
  ...props
}: PropsWithChildren<ButtonProps>) {
  return (
    <button
      type={type}
      className={`inline-flex cursor-pointer items-center justify-center rounded-xl px-4 py-2.5 text-sm font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 ${
        fullWidth ? 'w-full' : ''
      } ${variantStyles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}

export default Button
