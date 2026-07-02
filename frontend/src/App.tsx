import { RouterProvider } from '@tanstack/react-router'
import { router } from './routes'

export default function App(): JSX.Element {
  return <RouterProvider router={router} />
}
