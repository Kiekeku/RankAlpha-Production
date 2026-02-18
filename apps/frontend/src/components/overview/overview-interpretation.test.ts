import { describe, expect, it } from 'vitest'

import { buildOverviewImplication, computeOverviewPlaybook } from '@/components/overview/overview-interpretation'

describe('overview playbook', () => {
  it('defaults to defensive when nowcast is risk-off', () => {
    const playbook = computeOverviewPlaybook({
      nowcast_label: 'risk_off',
      overall_risk_off_score: 80,
      confidence: 0.8,
      coverage: 1,
      regime_rules_label: 'Trend',
      regime_rules_tags: [],
    })
    expect(playbook.bias).toBe('defensive')

    const text = buildOverviewImplication({
      nowcast_label: 'risk_off',
      overall_risk_off_score: 80,
      confidence: 0.8,
      coverage: 1,
      regime_rules_label: 'Trend',
      regime_rules_tags: [],
    })
    expect(text).toContain('Stay defensive')
  })

  it('maps Trend + risk-on to momentum', () => {
    const playbook = computeOverviewPlaybook({
      nowcast_label: 'risk_on',
      overall_risk_off_score: 25,
      confidence: 0.8,
      coverage: 1,
      regime_rules_label: 'Trend',
      regime_rules_tags: [],
    })
    expect(playbook.bias).toBe('momentum')
    expect(buildOverviewImplication({ nowcast_label: 'risk_on', overall_risk_off_score: 25, regime_rules_label: 'Trend' })).toContain(
      'momentum'
    )
  })

  it('does not force mean reversion in Trend when nowcast is neutral', () => {
    const playbook = computeOverviewPlaybook({
      nowcast_label: 'neutral',
      overall_risk_off_score: 50,
      confidence: 0.55,
      coverage: 1,
      regime_rules_label: 'Trend',
      regime_rules_tags: [],
    })
    expect(playbook.bias).toBe('balanced')
    expect(buildOverviewImplication({ nowcast_label: 'neutral', overall_risk_off_score: 50, regime_rules_label: 'Trend' })).toContain(
      'Trend backdrop'
    )
  })

  it('maps Chop + neutral to mean reversion', () => {
    const playbook = computeOverviewPlaybook({
      nowcast_label: 'neutral',
      overall_risk_off_score: 52,
      confidence: 0.55,
      coverage: 1,
      regime_rules_label: 'Chop',
      regime_rules_tags: [],
    })
    expect(playbook.bias).toBe('mean_reversion')
    expect(buildOverviewImplication({ nowcast_label: 'neutral', overall_risk_off_score: 52, regime_rules_label: 'Chop' })).toContain(
      'Prefer mean reversion'
    )
  })

  it('downshifts Chop + risk-on to balanced (avoid overly strong mean reversion call)', () => {
    const playbook = computeOverviewPlaybook({
      nowcast_label: 'risk_on',
      overall_risk_off_score: 30,
      confidence: 0.75,
      coverage: 1,
      regime_rules_label: 'Chop',
      regime_rules_tags: [],
    })
    expect(playbook.bias).toBe('balanced')
    expect(buildOverviewImplication({ nowcast_label: 'risk_on', overall_risk_off_score: 30, regime_rules_label: 'Chop' })).toContain(
      'Choppy tape'
    )
  })

  it('treats MeanReversionFavored tag as chop', () => {
    const playbook = computeOverviewPlaybook({
      nowcast_label: 'neutral',
      overall_risk_off_score: 55,
      confidence: 0.6,
      coverage: 1,
      regime_rules_label: 'Unknown',
      regime_rules_tags: ['MeanReversionFavored'],
    })
    expect(playbook.bias).toBe('mean_reversion')
  })

  it('treats DefensiveDrift tag as defensive overlay', () => {
    const playbook = computeOverviewPlaybook({
      nowcast_label: 'risk_on',
      overall_risk_off_score: 30,
      confidence: 0.75,
      coverage: 1,
      regime_rules_label: 'Trend',
      regime_rules_tags: ['DefensiveDrift'],
    })
    expect(playbook.bias).toBe('defensive')
  })

  it('adds a low-conviction sizing note near 50', () => {
    const text = buildOverviewImplication({
      nowcast_label: 'neutral',
      overall_risk_off_score: 50,
      confidence: 0.6,
      coverage: 1,
      regime_rules_label: 'Chop',
      regime_rules_tags: [],
    })
    expect(text).toContain('Low conviction - keep size small.')
  })
})

