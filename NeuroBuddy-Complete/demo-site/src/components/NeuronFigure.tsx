import { cx } from '../lib/cx'
import styles from './NeuronFigure.module.css'

type Props = {
  className?: string
  size?: 'hero' | 'stage' | 'mark' | 'ghost'
  alt?: string
}

export function NeuronFigure({ className, size = 'stage', alt }: Props) {
  return (
    <figure className={cx(styles.figure, styles[size], className)}>
      <div className={styles.stage}>
        <img
          src="/media/cyber-neuron.png"
          alt={alt ?? 'Biomechanical neuron with myelinated axon and chrome armature, on an off-white field'}
          width={1448}
          height={1086}
          decoding={size === 'hero' ? 'sync' : 'async'}
          fetchPriority={size === 'hero' ? 'high' : 'low'}
        />
      </div>
    </figure>
  )
}
