import React from 'react'
import { useNavigate } from 'react-router'
import { ArrowLeft } from 'lucide-react'

/* ============================================================
   Forgot Passcode — Static info screen
   ============================================================ */

const ADMIN_EMAIL = import.meta.env.VITE_ADMIN_EMAIL || 'admin@bens-shed.app'

export default function ForgotPasscode() {
  const navigate = useNavigate()

  return (
    <div
      className="flex items-center justify-center min-h-screen px-4"
      style={{ backgroundColor: '#F5F3EF' }}
    >
      <div className="w-full max-w-sm">
        {/* Back link */}
        <div className="mb-8">
          <button
            onClick={() => navigate('/login')}
            className="flex items-center gap-2 text-sm transition-opacity hover:opacity-70"
            style={{ color: '#6B7F5E' }}
          >
            <ArrowLeft className="w-4 h-4" />
            Back to the door
          </button>
        </div>

        {/* Card */}
        <div
          className="rounded-lg p-8"
          style={{ backgroundColor: '#EDEAE4' }}
        >
          {/* Heading */}
          <h1
            className="text-2xl font-semibold mb-4"
            style={{ color: '#1A1A1A' }}
          >
            Lost the code?
          </h1>

          {/* Body */}
          <p
            className="text-sm mb-6 leading-relaxed"
            style={{ color: '#6B6B6B' }}
          >
            Passcodes are set by the person who built this. Drop them a line.
          </p>

          {/* Contact */}
          <div>
            <div
              className="text-xs uppercase tracking-wide mb-2"
              style={{ color: '#6B7F5E' }}
            >
              Contact
            </div>
            <a
              href={`mailto:${ADMIN_EMAIL}`}
              className="text-sm font-medium transition-opacity hover:opacity-70"
              style={{ color: '#1A1A1A' }}
            >
              {ADMIN_EMAIL}
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
