import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import {
  isFullPageRedirectPath,
  navigateToFullPagePath,
  resolvePostLoginPath,
} from "../utils/loginRedirect";

/** Navigate after auth — OpenAPI docs use a full server page load, not HashRouter. */
export function PostLoginRedirect() {
  const location = useLocation();
  const target = resolvePostLoginPath(location);
  const [loopBlocked, setLoopBlocked] = useState(false);

  useEffect(() => {
    if (!isFullPageRedirectPath(target)) return;
    if (!navigateToFullPagePath(target, "replace")) {
      setLoopBlocked(true);
    }
  }, [target]);

  if (isFullPageRedirectPath(target)) {
    if (loopBlocked) {
      return <Navigate to="/chat" replace />;
    }
    return null;
  }
  return <Navigate to={target} replace />;
}
