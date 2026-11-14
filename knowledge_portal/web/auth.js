const form=document.getElementById("auth-form"),mode=form.dataset.mode;
let token=location.hash.slice(1);if(token)history.replaceState(null,"",location.pathname);
form.onsubmit=async e=>{e.preventDefault();const button=document.getElementById("submit"),message=document.getElementById("message");button.disabled=true;message.textContent="";
try{const r=await fetch("/api/"+mode,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:document.getElementById("username").value,password:document.getElementById("password").value,token})});const x=await r.json();if(!r.ok)throw Error(x.error);document.getElementById("password").value="";location.replace("/");}
catch(error){message.textContent=error.message;button.disabled=false;}};
